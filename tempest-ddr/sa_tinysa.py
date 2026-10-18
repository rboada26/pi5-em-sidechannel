#!/usr/bin/env python3
"""
sa_tinysa.py -- Drive a tinySA Ultra+ (Zeenko ZS-407) over USB from YOUR computer.

This runs on the laptop the tinySA is plugged into, NOT in the cloud and NOT on the
Pi. It talks to the analyzer over its USB serial console and captures traces for the
tempest-ddr Phase 1 experiment. No GUI needed.

The tinySA appears as a USB CDC serial port (STMicro VID 0x0483). Commands used
(from tinysa.org USB interface docs):
  scan {start} {stop} [points<=290] [outmask]   outmask 3 = freq+dBm, text
  sweep start|stop|center|span {Hz}
  rbw auto|3..600                                 (kHz)
  pause / resume
The console echoes input and ends each reply with a 'ch>' prompt.

Subcommands:
  ports                      list candidate serial ports
  info                       print firmware version/info
  peak    --start --stop     one scan; print the strongest line (find your tone)
  sweep   --start --stop --out f.csv
                             one scan -> CSV (freq,dBm) for  rx_sa.py sweep
  watch   --start --stop --secs S --out log.csv
                             repeatedly scan a narrow span; log (t, peak_Hz, peak_dBm)
                             -- this is how you record an FSK transmission
  decode  log.csv --freqs f0,f1 --symbol-ms T --nbits N [--expect BITS]
                             turn a watch-log into bits (finds symbol phase itself;
                             no hardware trigger into the tinySA needed)

Typical Phase 1 flow (details in README, "PATH A"):
  1) python sa_tinysa.py sweep --start 100k --stop 30M --out on.csv   # tx running
     python sa_tinysa.py sweep --start 100k --stop 30M --out off.csv  # tx stopped
     python rx_sa.py sweep --trace on.csv --off off.csv               # find the line
  2) send two long tones on the Pi, confirm the peak moves:
     python sa_tinysa.py peak --start 500k --stop 3M                   # while tx --fsk
  3) record and decode a payload:
     python sa_tinysa.py watch --start 500k --stop 3M --secs 20 --out fsk.csv
     python sa_tinysa.py decode fsk.csv --freqs 1M,2M --symbol-ms 1000 --nbits 8

Capture needs pyserial ( pip install pyserial ). decode needs only the stdlib
(numpy used if present, else a pure-python fallback).
"""
import argparse
import sys
import time
import re

_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
TINYSA_VID = 0x0483  # STMicroelectronics virtual COM


# ---------------------------------------------------------------- serial layer
def _import_serial():
    try:
        import serial
        from serial.tools import list_ports
        return serial, list_ports
    except Exception:
        sys.exit("pyserial not installed. Run:  pip install pyserial")


def parse_freq(s):
    """'500k' / '12M' / '1.5G' / '100000' -> float Hz."""
    s = str(s).strip()
    m = re.fullmatch(r"([-+]?\d*\.?\d+)\s*([kKmMgG]?)", s)
    if not m:
        raise argparse.ArgumentTypeError(f"bad frequency {s!r}")
    val = float(m.group(1))
    mul = {"": 1, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "g": 1e9, "G": 1e9}[m.group(2)]
    return val * mul


def find_port(prefer=None):
    serial, list_ports = _import_serial()
    cands = list(list_ports.comports())
    if prefer:
        return prefer
    # 1) match tinySA's VID
    for p in cands:
        if (p.vid == TINYSA_VID) or ("tinysa" in (p.description or "").lower()):
            return p.device
    # 2) common device names
    for p in cands:
        d = p.device
        if any(tok in d for tok in ("usbmodem", "ttyACM", "ttyUSB")) or d.upper().startswith("COM"):
            return d
    return cands[0].device if cands else None


class TinySA:
    def __init__(self, port=None, baud=115200, timeout=2.0):
        serial, _ = _import_serial()
        self.port = port or find_port()
        if not self.port:
            sys.exit("no serial port found. Plug in the tinySA, or pass --port.")
        self.ser = serial.Serial(self.port, baud, timeout=timeout)
        time.sleep(0.2)
        self.ser.reset_input_buffer()

    def cmd(self, s, settle=0.0):
        """Send a command, return the reply text up to the 'ch>' prompt."""
        self.ser.reset_input_buffer()
        self.ser.write((s + "\r\n").encode())
        if settle:
            time.sleep(settle)
        buf = bytearray()
        deadline = time.time() + 15.0
        while time.time() < deadline:
            chunk = self.ser.read(4096)
            if chunk:
                buf += chunk
                if b"ch>" in buf:
                    break
            elif buf:
                break
        text = buf.decode(errors="replace")
        # strip the echoed command line and the trailing prompt
        lines = [ln for ln in text.splitlines() if ln.strip() not in (s, "ch>")]
        return "\n".join(ln for ln in lines if ln.strip() != "ch>")

    def set_rbw(self, rbw):
        if rbw:
            self.cmd(f"rbw {rbw}")

    def scan(self, start, stop, points=290, rbw=None):
        """Return (freqs[Hz], levels[dBm]) via 'scan ... 3' text output."""
        points = max(2, min(int(points), 290))
        self.set_rbw(rbw)
        reply = self.cmd(f"scan {int(start)} {int(stop)} {points} 3", settle=0.0)
        fs, ys = [], []
        for ln in reply.splitlines():
            toks = _NUM.findall(ln)
            if len(toks) >= 2:
                try:
                    f = float(toks[0]); y = float(toks[1])
                except ValueError:
                    continue
                fs.append(f); ys.append(y)
        return fs, ys

    def close(self):
        try:
            self.cmd("resume")
            self.ser.close()
        except Exception:
            pass


# ---------------------------------------------------------------- subcommands
def do_ports(args):
    serial, list_ports = _import_serial()
    rows = list(list_ports.comports())
    if not rows:
        print("no serial ports found")
        return
    for p in rows:
        vid = f"{p.vid:04x}" if p.vid is not None else "----"
        star = "  <-- likely tinySA" if p.vid == TINYSA_VID else ""
        print(f"{p.device:24s} vid={vid} {p.description}{star}")


def do_info(args):
    sa = TinySA(args.port)
    for c in ("version", "info"):
        print(f"--- {c} ---")
        print(sa.cmd(c))
    sa.close()


def _peak(fs, ys):
    if not fs:
        return None, None
    k = max(range(len(ys)), key=lambda i: ys[i])
    return fs[k], ys[k]


def do_peak(args):
    sa = TinySA(args.port)
    fs, ys = sa.scan(args.start, args.stop, args.points, args.rbw)
    f, y = _peak(fs, ys)
    sa.close()
    if f is None:
        sys.exit("no data returned; check the connection and span")
    print(f"peak: {f/1e6:.4f} MHz  {y:.1f} dBm   "
          f"(span {args.start/1e6:.3f}-{args.stop/1e6:.3f} MHz, {len(fs)} pts)")


def do_sweep(args):
    sa = TinySA(args.port)
    fs, ys = sa.scan(args.start, args.stop, args.points, args.rbw)
    sa.close()
    if not fs:
        sys.exit("no data returned")
    with open(args.out, "w") as fh:
        fh.write("Frequency(Hz),Amplitude(dBm)\n")
        for f, y in zip(fs, ys):
            fh.write(f"{f:.1f},{y:.3f}\n")
    f, y = _peak(fs, ys)
    print(f"wrote {args.out}: {len(fs)} points; peak {f/1e6:.4f} MHz {y:.1f} dBm")


def do_watch(args):
    sa = TinySA(args.port)
    t0 = time.monotonic()
    n = 0
    with open(args.out, "w") as fh:
        fh.write("t_s,peak_Hz,peak_dBm\n")
        last_print = 0.0
        while time.monotonic() - t0 < args.secs:
            fs, ys = sa.scan(args.start, args.stop, args.points, args.rbw)
            t = time.monotonic() - t0
            f, y = _peak(fs, ys)
            if f is not None:
                fh.write(f"{t:.4f},{f:.1f},{y:.3f}\n")
                fh.flush()
                n += 1
                if t - last_print >= 0.5:
                    print(f"\r  t={t:6.2f}s  peak={f/1e6:7.4f} MHz  {y:6.1f} dBm  "
                          f"({n} scans)", end="", flush=True)
                    last_print = t
    sa.close()
    print(f"\nwrote {args.out}: {n} scans over {args.secs}s "
          f"(~{n/max(args.secs,1e-9):.1f} scans/s)")


# ---- decode a watch-log into bits (symbol phase found automatically) --------
def _read_watch(path):
    ts, fs = [], []
    with open(path) as fh:
        for ln in fh:
            toks = _NUM.findall(ln)
            if len(toks) >= 2 and _NUM.fullmatch(toks[0]):
                try:
                    t = float(toks[0]); f = float(toks[1])
                except ValueError:
                    continue
                ts.append(t); fs.append(f)
    return ts, fs


def do_decode(args):
    ts, fs = _read_watch(args.log)
    if len(ts) < 2:
        sys.exit("watch-log too short")
    tones = [parse_freq(x) for x in args.freqs.split(",")]
    sym_s = args.symbol_ms / 1000.0
    nbits = args.nbits

    # map every sample to its nearest tone index
    def nearest(f):
        return min(range(len(tones)), key=lambda i: abs(f - tones[i]))
    sidx = [nearest(f) for f in fs]

    # search the symbol-grid phase offset that gives the cleanest segmentation.
    # score = fraction of samples that agree with their segment's majority tone.
    t_start = ts[0]
    best = None
    steps = 40
    for ph in range(steps):
        off = (ph / steps) * sym_s
        # assign each sample to a symbol slot
        slot_of = [int((t - t_start - off) // sym_s) for t in ts]
        slots = {}
        for s, si in zip(slot_of, sidx):
            if s < 0:
                continue
            slots.setdefault(s, []).append(si)
        if not slots:
            continue
        agree = 0
        total = 0
        bits_by_slot = {}
        counts_by_slot = {}
        for s, lst in slots.items():
            maj = max(set(lst), key=lst.count)
            bits_by_slot[s] = maj
            counts_by_slot[s] = len(lst)
            agree += lst.count(maj)
            total += len(lst)
        score = agree / total if total else 0
        if best is None or score > best[0]:
            best = (score, off, bits_by_slot, counts_by_slot)

    score, off, bits_by_slot, counts_by_slot = best
    # Keep only well-populated, contiguous slots (drop partial edge symbols that
    # a mid-symbol capture start/stop produces). Build the FULL decoded stream;
    # without a trigger we don't know which symbol is "first", so we print the
    # whole stream and (if --expect) locate the payload inside it.
    if counts_by_slot:
        med = sorted(counts_by_slot.values())[len(counts_by_slot)//2]
    else:
        med = 1
    order = sorted(bits_by_slot)
    kept = [s for s in order if counts_by_slot.get(s, 0) >= max(1, 0.4 * med)]
    # take the longest run of consecutive slots
    run, best_run = [], []
    for s in kept:
        if run and s == run[-1] + 1:
            run.append(s)
        else:
            run = [s]
        if len(run) > len(best_run):
            best_run = run[:]
    stream = "".join(str(bits_by_slot[s] & 1) for s in best_run)

    print(f"decode: {len(ts)} samples, tones {[f/1e6 for f in tones]} MHz, "
          f"symbol {args.symbol_ms} ms")
    print(f"  phase offset {off*1000:.0f} ms, segmentation agreement {score*100:.0f}%")
    print(f"  decoded stream ({len(stream)} symbols): {stream}")

    if args.expect:
        exp = args.expect.strip()
        if len(exp) > len(stream):
            print(f"  expected {len(exp)} bits but only {len(stream)} decoded; "
                  f"capture longer or lengthen symbols")
            return
        # slide expected over the stream, report best (lowest bit-error) alignment
        best_pos, best_err = 0, len(exp) + 1
        for i in range(len(stream) - len(exp) + 1):
            err = sum(1 for a, b in zip(exp, stream[i:i+len(exp)]) if a != b)
            if err < best_err:
                best_err, best_pos = err, i
        print(f"  expected:       {exp}")
        print(f"  best match at offset {best_pos}: {stream[best_pos:best_pos+len(exp)]} "
              f"-> {best_err}/{len(exp)} bit errors "
              f"({'PASS' if best_err == 0 else 'MISMATCH'})")


# ---------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port (default: autodetect)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ports", help="list serial ports")
    sub.add_parser("info", help="print tinySA version/info")

    def span(p):
        p.add_argument("--start", type=parse_freq, required=True, help="e.g. 500k")
        p.add_argument("--stop", type=parse_freq, required=True, help="e.g. 3M")
        p.add_argument("--points", type=int, default=290, help="<=290 (default 290)")
        p.add_argument("--rbw", help="kHz or 'auto' (default: leave as set)")

    p = sub.add_parser("peak", help="one scan, print strongest line"); span(p)
    p = sub.add_parser("sweep", help="one scan -> CSV"); span(p)
    p.add_argument("--out", required=True)
    p = sub.add_parser("watch", help="repeated scans -> time log"); span(p)
    p.add_argument("--secs", type=float, required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("decode", help="watch-log -> bits")
    p.add_argument("log")
    p.add_argument("--freqs", required=True, help="tone table, e.g. 1M,2M")
    p.add_argument("--symbol-ms", type=float, required=True)
    p.add_argument("--nbits", type=int, required=True)
    p.add_argument("--expect")

    args = ap.parse_args()
    {"ports": do_ports, "info": do_info, "peak": do_peak, "sweep": do_sweep,
     "watch": do_watch, "decode": do_decode}[args.cmd](args)


if __name__ == "__main__":
    main()
