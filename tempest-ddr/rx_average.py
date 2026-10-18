#!/usr/bin/env python3
"""
rx_average.py -- Receiver-side analysis for the DDR/PCIe "antenna" transmitter.

Goal: take a wideband IQ capture made with an SDR while tx_ddr was running, and
(1) find the data-dependent carrier, (2) align the repeated frames using the GPIO
frame-trigger channel, and (3) coherently average many frames so a weak, buried
signal climbs out of the noise -- exactly the periodic-averaging trick Kuhn &
Anderson and van Eck rely on.

Two input styles are supported:

  A) IQ + trigger-log  (recommended, decouples SDR from GPIO):
       --iq capture.cf32 --fs 8e6 --fc 300e6
       --triglog trig.csv        # monotonic-ns timestamps of each frame start
     You capture IQ on the SDR host and, separately, log the Pi's GPIO trigger
     edges (e.g. from a second GPIO wired to an input, or from tx_ddr's own
     stderr timestamps). Alignment is by timestamp.

  B) IQ + a trigger tone embedded as an extra channel is NOT assumed here; if you
     have no trigger log, use --autocorr to find the frame period from the signal
     itself (works when SNR is already decent) and average on that period.

Input IQ format: interleaved float32 (I,Q,I,Q,...), i.e. numpy complex64 on disk
(".cf32"/".iq"). That is what `hackrf_transfer`→conversion, `rtl_sdr`→conversion,
GNU Radio, and SoapySDR all can produce. Use --int8 or --uint8 for raw RTL-SDR
(uint8) or HackRF (int8) captures and it will convert.

This script does NOT talk to the SDR. Capture with your tool of choice; this reads
the file. Keeping capture and analysis separate means the capture step adds no
Python/CPU noise near the DUT.

Outputs: a PSD plot (find the carrier), a spectrogram, and -- if a frame period is
known -- an averaged-magnitude frame plot and the recovered per-symbol levels,
plus a PNG for each. Numbers that matter (carrier freq, per-symbol mean levels,
estimated bit decisions) are printed and written to <out>/summary.json.
"""
import argparse
import json
import os
import sys
import numpy as np


def load_iq(path, fmt):
    """Load interleaved IQ into complex64. fmt in {cf32,int8,uint8}."""
    if fmt == "cf32":
        raw = np.fromfile(path, dtype=np.float32)
        if raw.size % 2:
            raw = raw[:-1]
        iq = raw.astype(np.float32).view(np.complex64)
        return iq
    if fmt == "int8":
        raw = np.fromfile(path, dtype=np.int8).astype(np.float32)
        if raw.size % 2:
            raw = raw[:-1]
        return (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
    if fmt == "uint8":
        raw = np.fromfile(path, dtype=np.uint8).astype(np.float32) - 127.5
        if raw.size % 2:
            raw = raw[:-1]
        return (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
    raise ValueError(f"unknown fmt {fmt}")


def psd(iq, fs, fc, nfft=65536):
    """Welch-ish PSD. Returns (freqs_hz_absolute, power_db)."""
    nfft = min(nfft, len(iq))
    if nfft < 16:
        raise SystemExit("capture too short for a PSD")
    win = np.hanning(nfft)
    nseg = len(iq) // nfft
    acc = np.zeros(nfft)
    for s in range(nseg):
        seg = iq[s * nfft:(s + 1) * nfft] * win
        acc += np.abs(np.fft.fftshift(np.fft.fft(seg))) ** 2
    acc /= max(nseg, 1)
    acc /= (np.sum(win ** 2) * fs)
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs)) + fc
    power_db = 10 * np.log10(acc + 1e-20)
    return freqs, power_db


def find_carrier(freqs, power_db, fc, guard_hz=5e3):
    """Pick the strongest bin, ignoring a guard band around DC (fc) where the
    SDR's own LO leakage/1-f noise sits."""
    off = np.abs(freqs - fc)
    mask = off > guard_hz
    idx = np.argmax(np.where(mask, power_db, -np.inf))
    return freqs[idx], power_db[idx]


def tune_and_decimate(iq, fs, f_offset, bw):
    """Mix the carrier at (fc+f_offset) down to baseband and low-pass/decimate to
    ~bw. Returns (bb, fs_bb). Simple FIR via FFT overlap not needed at these
    rates; use a boxcar decimator after mixing."""
    n = np.arange(len(iq))
    lo = np.exp(-2j * np.pi * (f_offset / fs) * n).astype(np.complex64)
    mixed = iq * lo
    dec = max(1, int(fs // (bw * 2)))
    # cheap anti-alias: moving average of length `dec` then downsample
    if dec > 1:
        kernel = np.ones(dec, dtype=np.float32) / dec
        mixed = np.convolve(mixed, kernel, mode="same")
        bb = mixed[::dec]
        fs_bb = fs / dec
    else:
        bb = mixed
        fs_bb = fs
    return bb.astype(np.complex64), fs_bb


def frame_starts_from_triglog(triglog, fs_bb, t0_ns=None):
    """Read monotonic-ns frame-start timestamps, convert to baseband sample
    indices relative to the first. Assumes the IQ capture and the trig log share
    a start reference; if not exact, --autocorr is more robust."""
    ts = []
    with open(triglog) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # accept "ns" or "ns,anything"
            ts.append(int(line.split(",")[0]))
    if not ts:
        raise SystemExit("trig log empty")
    ts = np.array(ts, dtype=np.int64)
    base = t0_ns if t0_ns is not None else ts[0]
    rel_s = (ts - base) / 1e9
    return np.round(rel_s * fs_bb).astype(np.int64)


def estimate_period_autocorr(mag, fs_bb, min_hz=1.0, max_hz=5000.0):
    """Find the frame repetition period from the autocorrelation of the envelope."""
    x = mag - np.mean(mag)
    # limit length for speed
    N = min(len(x), 1 << 20)
    x = x[:N]
    ac = np.correlate(x, x, mode="full")[N - 1:]
    lo = int(fs_bb / max_hz)
    hi = int(fs_bb / min_hz)
    hi = min(hi, len(ac) - 1)
    if hi <= lo + 1:
        return None
    lag = lo + int(np.argmax(ac[lo:hi]))
    return lag  # in baseband samples


def average_frames(mag, starts, frame_len):
    """Coherently (in magnitude) average frames of length frame_len at the given
    start indices. Returns the averaged frame and the count used."""
    acc = np.zeros(frame_len)
    used = 0
    for s in starts:
        if s < 0 or s + frame_len > len(mag):
            continue
        acc += mag[s:s + frame_len]
        used += 1
    if used == 0:
        raise SystemExit("no frames fit inside the capture; check fs/period")
    return acc / used, used


def decide_symbols(frame, nbits):
    """Split an averaged frame into nbits equal slots, take each slot's mean, and
    threshold at the midpoint between the min and max slot means -> bit guesses."""
    slot = len(frame) // nbits
    if slot == 0:
        return [], []
    levels = [float(np.mean(frame[i * slot:(i + 1) * slot])) for i in range(nbits)]
    lo, hi = min(levels), max(levels)
    thr = (lo + hi) / 2
    bits = [1 if lv > thr else 0 for lv in levels]
    return bits, levels


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iq", required=True, help="IQ capture file")
    ap.add_argument("--fmt", default="cf32", choices=["cf32", "int8", "uint8"],
                    help="sample format (default cf32 = complex64 on disk)")
    ap.add_argument("--fs", required=True, type=float, help="sample rate Hz")
    ap.add_argument("--fc", required=True, type=float, help="SDR center freq Hz")
    ap.add_argument("--triglog", help="CSV of monotonic-ns frame-start times")
    ap.add_argument("--t0", type=float, default=None,
                    help="monotonic-ns of IQ sample 0 (reference for triglog)")
    ap.add_argument("--autocorr", action="store_true",
                    help="estimate frame period from the signal instead of triglog")
    ap.add_argument("--nbits", type=int, default=8,
                    help="payload bits per frame (must match tx --bits length)")
    ap.add_argument("--carrier", type=float, default=None,
                    help="force carrier offset from fc in Hz (skip auto-detect)")
    ap.add_argument("--bw", type=float, default=50e3,
                    help="baseband bandwidth after downconversion (Hz)")
    ap.add_argument("--out", default="rx_out", help="output directory")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        have_plt = True
    except Exception as e:
        print(f"[warn] matplotlib unavailable ({e}); will write numbers only")
        have_plt = False

    iq = load_iq(args.iq, args.fmt)
    if len(iq) < 1024:
        raise SystemExit("capture too short")
    print(f"[info] loaded {len(iq)} samples, {len(iq)/args.fs:.3f} s at fs={args.fs/1e6:.3f} MHz")

    # 1) PSD -> carrier
    freqs, pdb = psd(iq, args.fs, args.fc)
    if args.carrier is not None:
        f_car = args.fc + args.carrier
        p_car = float(pdb[np.argmin(np.abs(freqs - f_car))])
    else:
        f_car, p_car = find_carrier(freqs, pdb, args.fc)
    f_offset = f_car - args.fc
    print(f"[info] carrier at {f_car/1e6:.4f} MHz  (offset {f_offset/1e3:+.1f} kHz, {p_car:.1f} dB)")

    if have_plt:
        plt.figure(figsize=(9, 4))
        plt.plot(freqs / 1e6, pdb, lw=0.6)
        plt.axvline(f_car / 1e6, color="r", ls="--", lw=0.8, label="carrier")
        plt.xlabel("MHz"); plt.ylabel("dB"); plt.title("PSD"); plt.legend()
        plt.tight_layout(); plt.savefig(f"{args.out}/psd.png", dpi=120); plt.close()

    # 2) downconvert to the carrier, envelope
    bb, fs_bb = tune_and_decimate(iq, args.fs, f_offset, args.bw)
    mag = np.abs(bb).astype(np.float32)
    print(f"[info] baseband fs={fs_bb/1e3:.1f} kHz, {len(mag)} samples")

    # 3) frame alignment
    period = None
    starts = None
    if args.triglog:
        starts = frame_starts_from_triglog(args.triglog, fs_bb, args.t0)
        if len(starts) >= 2:
            period = int(np.median(np.diff(starts)))
        print(f"[info] {len(starts)} frame starts from trig log; median period "
              f"{period} samp ({(period/fs_bb*1e3 if period else float('nan')):.2f} ms)")
    elif args.autocorr:
        period = estimate_period_autocorr(mag, fs_bb)
        if period is None:
            raise SystemExit("autocorr found no period in range; set --triglog")
        starts = np.arange(0, len(mag) - period, period, dtype=np.int64)
        print(f"[info] autocorr period {period} samp "
              f"({period/fs_bb*1e3:.2f} ms, {fs_bb/period:.1f} Hz frame rate), "
              f"{len(starts)} frames")
    else:
        print("[warn] no --triglog and no --autocorr: skipping frame averaging")

    summary = {
        "carrier_hz": f_car,
        "carrier_offset_hz": f_offset,
        "carrier_power_db": p_car,
        "fs_bb_hz": fs_bb,
        "n_samples": int(len(iq)),
    }

    if period and starts is not None and len(starts) >= 1:
        frame, used = average_frames(mag, starts, period)
        bits, levels = decide_symbols(frame, args.nbits)
        snr_proxy = (max(levels) - min(levels)) / (np.std(mag) + 1e-12) if levels else 0.0
        print(f"[info] averaged {used} frames")
        print(f"[result] per-symbol levels: {['%.3g' % v for v in levels]}")
        print(f"[result] bit guesses:       {''.join(map(str, bits))}")
        print(f"[result] level spread / noise proxy: {snr_proxy:.2f}")
        summary.update({
            "frames_averaged": used,
            "frame_period_samp": int(period),
            "symbol_levels": levels,
            "bit_guesses": bits,
            "level_spread_over_noise": float(snr_proxy),
        })
        if have_plt:
            plt.figure(figsize=(9, 4))
            t_ms = np.arange(len(frame)) / fs_bb * 1e3
            plt.plot(t_ms, frame, lw=0.8)
            slot = len(frame) // args.nbits
            for i in range(args.nbits):
                plt.axvline(i * slot / fs_bb * 1e3, color="k", ls=":", lw=0.4)
            plt.xlabel("ms into frame"); plt.ylabel("avg |bb|")
            plt.title(f"Averaged frame (n={used})  guesses={''.join(map(str,bits))}")
            plt.tight_layout(); plt.savefig(f"{args.out}/frame_avg.png", dpi=120); plt.close()

    with open(f"{args.out}/summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[info] wrote {args.out}/summary.json" + (" and PNGs" if have_plt else ""))


if __name__ == "__main__":
    main()
