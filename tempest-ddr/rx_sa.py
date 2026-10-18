#!/usr/bin/env python3
"""
rx_sa.py -- Analyze spectrum-analyzer trace exports for the tempest-ddr experiment.

Use this instead of rx_average.py when your receiver is a swept spectrum analyzer
(SA), not an SDR. An SA gives you power-vs-frequency (sweep mode) or, with span set
to 0, power-vs-time at one frequency (zero-span mode). It does NOT give IQ, so the
workflow is different -- but a swept SA in zero-span with external trigger and
trace averaging does the same periodic-averaging job rx_average.py did in software.

This script reads CSV traces the SA exports (USB stick / SCPI dump) and does two
jobs:

  sweep    : find the data-dependent carrier. Give it a trace taken while tx_ddr
             runs (ideally --carrier), optionally a second trace with tx OFF, and
             it reports the strongest line and (if given the OFF trace) the bins
             that appear only when tx runs -- the differential, which is the real
             leak, not the ambient RF.

  zerospan : decode the OOK payload. Give it one or more zero-span traces (power
             vs time at the carrier, each spanning one triggered frame). It
             averages them, splits the frame into N symbol slots, thresholds, and
             prints the recovered bits. If the SA already averaged on-screen,
             pass the single averaged trace; if you dumped many single-sweep
             traces, pass them all and this averages them.

CSV handling: vendors differ (Rigol, Siglent, Keysight, R&S, Anritsu, tinySA...).
The reader skips non-numeric header lines and takes the first two numeric columns
as (x, amplitude). Override with --xcol/--ycol if your file has more columns, or
--delim for tab/semicolon files. Amplitude is assumed to be dB/dBm (log); that is
fine for both finding peaks and OOK thresholding.

No instrument control here -- you capture on the SA and export. (If your SA has
SCPI over USB/LAN, tell me the model and I'll add a capture helper.)
"""
import argparse
import glob
import json
import os
import re
import sys
import numpy as np

_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def read_trace(path, xcol, ycol, delim):
    """Return (x, y) float arrays from an SA CSV, skipping header/metadata lines."""
    xs, ys = [], []
    with open(path, "r", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            parts = re.split(delim, s) if delim else re.split(r"[,\t;]", s)
            # need at least max(xcol,ycol)+1 numeric-looking fields
            if len(parts) <= max(xcol, ycol):
                continue
            xp, yp = parts[xcol].strip(), parts[ycol].strip()
            if not (_NUM.fullmatch(xp) and _NUM.fullmatch(yp)):
                continue  # header or label row
            xs.append(float(xp))
            ys.append(float(yp))
    if not xs:
        raise SystemExit(f"{path}: no numeric rows found "
                         f"(try --xcol/--ycol/--delim; first lines may be metadata)")
    return np.asarray(xs), np.asarray(ys)


def cmd_sweep(args):
    x, y = read_trace(args.trace, args.xcol, args.ycol, args.delim)
    # x is frequency (Hz, or whatever unit the file uses -- we don't care, we
    # report in the file's own units and also as an index).
    out = {"mode": "sweep", "trace": args.trace, "n_points": int(len(x))}

    if args.off:
        xo, yo = read_trace(args.off, args.xcol, args.ycol, args.delim)
        # align by nearest frequency if lengths/grids match closely
        if len(yo) == len(y):
            diff = y - yo
        else:
            yo_i = np.interp(x, xo, yo)
            diff = y - yo_i
        k = int(np.argmax(diff))
        out["carrier_x"] = float(x[k])
        out["carrier_delta_db"] = float(diff[k])
        out["on_db"] = float(y[k])
        out["off_db"] = float(y[k] - diff[k])
        # top few differential lines
        order = np.argsort(diff)[::-1][:8]
        out["top_differential"] = [
            {"x": float(x[i]), "delta_db": float(diff[i]), "on_db": float(y[i])}
            for i in order
        ]
        print(f"[sweep] strongest tx-ON-only line at x={x[k]:.6g} "
              f"(+{diff[k]:.1f} dB vs tx-off, on={y[k]:.1f} dB)")
        print("[sweep] top differential lines (x, +dB over off):")
        for d in out["top_differential"]:
            print(f"         {d['x']:.6g}   +{d['delta_db']:.1f} dB")
    else:
        k = int(np.argmax(y))
        out["carrier_x"] = float(x[k])
        out["peak_db"] = float(y[k])
        order = np.argsort(y)[::-1][:8]
        out["top_peaks"] = [{"x": float(x[i]), "db": float(y[i])} for i in order]
        print(f"[sweep] strongest line at x={x[k]:.6g} ({y[k]:.1f} dB)")
        print("[sweep] (no tx-off trace given; this is the raw peak, which may be "
              "ambient RF. Re-run with --off <trace taken with tx stopped> to get "
              "the data-dependent line.)")
        for d in out["top_peaks"]:
            print(f"         {d['x']:.6g}   {d['db']:.1f} dB")

    _maybe_plot_sweep(args, x, y, out)
    _write_summary(args, out)
    return out


def db_to_lin(db):
    return 10.0 ** (np.asarray(db) / 10.0)


def cmd_zerospan(args):
    files = []
    for pat in args.traces:
        files.extend(sorted(glob.glob(pat)))
    if not files:
        raise SystemExit("no zero-span traces matched")
    # read all; resample each to a common length (the shortest) so we can average
    ys = []
    xref = None
    for p in files:
        x, y = read_trace(p, args.xcol, args.ycol, args.delim)
        ys.append((x, y))
    minlen = min(len(y) for _, y in ys)
    # average in LINEAR power, then back to dB (correct way to average power)
    acc = np.zeros(minlen)
    for x, y in ys:
        if len(y) != minlen:
            xn = np.linspace(x[0], x[-1], minlen)
            y = np.interp(xn, x, y)
        acc += db_to_lin(y)
    acc /= len(ys)
    frame_db = 10.0 * np.log10(acc + 1e-30)
    frame_lin = acc

    nbits = args.nbits
    slot = len(frame_lin) // nbits
    if slot == 0:
        raise SystemExit(f"trace too short ({len(frame_lin)} pts) for {nbits} symbols")

    # per-symbol level = mean LINEAR power in the central 60% of each slot
    # (avoid edges where the SA's envelope is still settling between symbols)
    lo_frac, hi_frac = 0.2, 0.8
    levels_lin, levels_db = [], []
    for i in range(nbits):
        seg = frame_lin[i * slot:(i + 1) * slot]
        a = int(len(seg) * lo_frac)
        b = int(len(seg) * hi_frac)
        core = seg[a:b] if b > a else seg
        m = float(np.mean(core))
        levels_lin.append(m)
        levels_db.append(10.0 * np.log10(m + 1e-30))

    lo, hi = min(levels_lin), max(levels_lin)
    # threshold midway in dB (geometric mean in linear) -- robust for OOK
    thr_lin = (lo * hi) ** 0.5
    bits = [1 if lv > thr_lin else 0 for lv in levels_lin]
    contrast_db = 10.0 * np.log10(hi / lo) if lo > 0 else float("inf")

    print(f"[zerospan] averaged {len(files)} trace(s), {len(frame_lin)} points, "
          f"{nbits} symbols")
    print(f"[zerospan] per-symbol level (dB): {['%.1f' % v for v in levels_db]}")
    print(f"[zerospan] mark/space contrast:   {contrast_db:.1f} dB")
    print(f"[zerospan] recovered bits:        {''.join(map(str, bits))}")
    if args.expect:
        exp = args.expect.strip()
        if len(exp) == len(bits):
            nerr = sum(1 for a, b in zip(exp, map(str, bits)) if a != b)
            print(f"[zerospan] expected:              {exp}")
            print(f"[zerospan] bit errors:            {nerr}/{len(exp)} "
                  f"({'PASS' if nerr == 0 else 'MISMATCH'})")

    out = {
        "mode": "zerospan",
        "n_traces": len(files),
        "n_points": int(len(frame_lin)),
        "nbits": nbits,
        "symbol_levels_db": levels_db,
        "contrast_db": contrast_db,
        "bits": bits,
    }
    if args.expect:
        out["expected"] = args.expect.strip()
    _maybe_plot_zerospan(args, frame_db, slot, nbits, bits)
    _write_summary(args, out)
    return out


def cmd_fsk(args):
    """Decode FSK: each symbol is one swept trace; the strongest peak's frequency
    maps to the nearest tone in --freqs. One trace per symbol, in order."""
    freqs = [float(x) for x in args.freqs.split(",")]
    if len(freqs) < 2:
        raise SystemExit("--freqs needs >=2 tones")
    files = []
    for pat in args.traces:
        files.extend(sorted(glob.glob(pat)))
    if not files:
        raise SystemExit("no per-symbol traces matched")

    sym_bits, peaks = [], []
    for p in files:
        x, y = read_trace(p, args.xcol, args.ycol, args.delim)
        k = int(np.argmax(y))
        fpk = float(x[k])
        # nearest tone -> symbol index -> bit (2-FSK: index 0/1)
        sidx = int(np.argmin([abs(fpk - f) for f in freqs]))
        peaks.append(fpk)
        sym_bits.append(sidx & 1)

    bits = "".join(str(b) for b in sym_bits)
    print(f"[fsk] {len(files)} symbol trace(s); tones {freqs}")
    for p, fpk, b in zip(files, peaks, sym_bits):
        print(f"      {os.path.basename(p):20s} peak={fpk:.6g} -> bit {b}")
    print(f"[fsk] recovered bits: {bits}")
    out = {"mode": "fsk", "freqs": freqs, "peaks": peaks, "bits": sym_bits}
    if args.expect:
        exp = args.expect.strip()
        if len(exp) == len(bits):
            nerr = sum(1 for a, b in zip(exp, bits) if a != b)
            print(f"[fsk] expected:       {exp}")
            print(f"[fsk] bit errors:     {nerr}/{len(exp)} "
                  f"({'PASS' if nerr == 0 else 'MISMATCH'})")
            out["expected"] = exp
    _write_summary(args, out)
    return out


def _plt():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except Exception as e:
        print(f"[warn] matplotlib unavailable ({e}); skipping plot")
        return None


def _maybe_plot_sweep(args, x, y, out):
    plt = _plt()
    if not plt:
        return
    plt.figure(figsize=(9, 4))
    plt.plot(x, y, lw=0.6)
    plt.axvline(out["carrier_x"], color="r", ls="--", lw=0.8, label="carrier")
    plt.xlabel("frequency (file units)"); plt.ylabel("dB")
    plt.title("SA sweep"); plt.legend(); plt.tight_layout()
    plt.savefig(os.path.join(args.out, "sa_sweep.png"), dpi=120); plt.close()


def _maybe_plot_zerospan(args, frame_db, slot, nbits, bits):
    plt = _plt()
    if not plt:
        return
    plt.figure(figsize=(9, 4))
    plt.plot(frame_db, lw=0.8)
    for i in range(nbits):
        plt.axvline(i * slot, color="k", ls=":", lw=0.4)
    plt.xlabel("trace point (time into frame)"); plt.ylabel("avg power (dB)")
    plt.title(f"Zero-span averaged frame  bits={''.join(map(str, bits))}")
    plt.tight_layout()
    plt.savefig(os.path.join(args.out, "sa_zerospan.png"), dpi=120); plt.close()


def _write_summary(args, out):
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"[info] wrote {os.path.join(args.out, 'summary.json')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--xcol", type=int, default=0, help="0-based x column (default 0)")
    common.add_argument("--ycol", type=int, default=1, help="0-based amplitude column (default 1)")
    common.add_argument("--delim", default=None,
                        help="field delimiter regex (default: any of , tab ;)")
    common.add_argument("--out", default="sa_out", help="output directory")

    s = sub.add_parser("sweep", parents=[common],
                       help="find the data-dependent carrier from a swept trace")
    s.add_argument("--trace", required=True, help="swept CSV with tx running")
    s.add_argument("--off", help="swept CSV with tx stopped (for differencing)")

    z = sub.add_parser("zerospan", parents=[common],
                       help="decode OOK from zero-span trace(s)")
    z.add_argument("traces", nargs="+",
                   help="one averaged trace, or many single-frame traces / globs")
    z.add_argument("--nbits", type=int, default=8, help="symbols per frame (match tx --bits)")
    z.add_argument("--expect", help="expected bit string, to report BER")

    fk = sub.add_parser("fsk", parents=[common],
                        help="decode FSK: one swept trace per symbol, peak -> tone")
    fk.add_argument("traces", nargs="+",
                    help="per-symbol swept traces, in order (globs sort lexically)")
    fk.add_argument("--freqs", required=True,
                    help="comma-separated tone table, must match tx --fsk")
    fk.add_argument("--expect", help="expected bit string, to report BER")

    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    if args.cmd == "sweep":
        cmd_sweep(args)
    elif args.cmd == "zerospan":
        cmd_zerospan(args)
    elif args.cmd == "fsk":
        cmd_fsk(args)


if __name__ == "__main__":
    main()
