# Phase 1 capture log

## Setup
- Analyzer: tinySA Ultra+ ZS407, fw tinySA4_v1.4-217-gc5dd31f, /dev/ttyACM0
- Pi 5 (4GB, Debian 13), all cores governor=performance @2.4GHz, throttled=0x0, ~52C
- tx_ddr built on Pi (libgpiod v2, /dev/gpiochip0), whip antenna near board (no cage)
- sa_tinysa.py scan parser VALIDATED on real hw (3-col output <Hz> <dBm> <extra>,
  echo-stripped in cmd(); no code change needed)

## Step 1 — board radiates? (on/off differencing, `--carrier`)
- Full span 100k-30M, 290pts (coarse 103kHz bins): noise yardstick OFF-vs-OFF std ~4 dB.
  Only reproducible coarse candidate ~18.0 MHz (+10/+9.5 dB both pairs).
- Zoom 16-20M and 18.5-20.5M: strong ON-only energy, peak wanders 19.14<->19.63 MHz
  between runs (+26 to +27 dB over off, ON peak ~-58 to -63 dBm; off floor ~-85 to -90).
- CONCLUSION: `--carrier` = broadband DRAM-activity emission, ON-only, strongest in
  ~18.5-20.5 MHz. Not a narrow stable tone (expected: continuous streaming = broadband).
  Board clearly radiates data/activity-dependent signal vs ambient. Step 1 PASS.
- Files: on.csv/off.csv, on2.csv/off2.csv (full), on_zoom*/off_zoom* (16-20M, 18.5-20.5M)

## Step 2 attempt — FSK by tick-rate: DOES NOT WORK on this board
- BUG FOUND+FIXED in tx_ddr.c: --fsk used strtod() which ignored k/M/G suffix, so
  "1M,2M" became 1 Hz/2 Hz. Added parse_si() helper; banner now "1000000 2000000 Hz".
- Steady tick at 1/2 MHz (whip): +4-5 dB at tone, noise std ~2.6 dB -> ~noise.
- Steady tick at 12/18 MHz (whip): +2.5-4.5 dB AT the tick rate (noise), BUT strong
  broadband ON bumps at 17.7 MHz (+14) / 18.75 MHz (+15.5) INDEPENDENT of tick rate.
- Conclusion: the memory-store burst radiates a broadband hump ~16-19 MHz (its coupling
  resonance); the tick REPETITION RATE barely shows as a line. FSK-by-frequency (runbook
  primary) does not shift the emitted freq on Pi5+whip. Activity-gated ~18 MHz emission
  (ON vs OFF, +15..+27 dB) is the real channel -> OOK is the right scheme here.
- do_watch() limitation: records only per-scan PEAK (not power AT tone freqs), and
  tinySA scans ~0.5/s vs 1 symbol/s -> undersampled. decode path needs IQ (SDR).

## HackRF ANT500 antenna on tinySA (vs stock whip)
- ANT500 is specced 75 MHz-1 GHz; electrically tiny at our band.
- 16-20 MHz carrier: ON-only +15.5 dB but max ON only -74 dBm (whip gave -58 dBm) -> WORSE at 18 MHz.
- 2 MHz tick: +5 dB (noise) -> no better than whip. Antenna swap does NOT help FSK.
- Decision: keep WHIP for any tinySA work; the real unlock is the HackRF SDR (continuous
  IQ, fine time resolution, sensitivity) -> OOK decode of the 18 MHz activity emission.

## CORRECTION + real result (averaged differencing)
- The ~18 MHz "emission" (Step 1 above) DID NOT survive averaging: 16 ON vs 16 OFF
  avg -> 0.8 +/- 1.0 dB across 10-25 MHz; strongest single-sweep peak was with carrier
  OFF (-55.6 dBm). The 15-20 MHz band is AMBIENT HF (shortwave/ham), not the Pi.
  Single-pair differencing was fooled by intermittent ambient. ANT500 and whip both ~0.
- Rigorous method: K interleaved ON/OFF rounds (toggle carrier each round so ambient
  cancels) + per-bin Welch t. Surveyed lo/vhf/uhf:
    0.1-30 MHz : nothing (max t=3.2, chance-level across 290 bins)
    30-120 MHz : marginal (t=4.2 @ 54.6 MHz)
    120-300 MHz: REAL, clustered -> ~263.4 MHz and ~286.8 MHz
- UHF zoom 255-295 MHz, K=12: 286.8 MHz t up to 9.9 (+3.4..4.2 dB, ON ~-72 dBm);
  263.4 MHz t up to 7.9 (+3..4.7 dB, ON ~-77 dBm). band median|diff|=0.84 dB -> 4-5 sigma.
- Waterfall (280-293 MHz, 20 ON then 20 OFF): 286.8 line +4.4 dB brighter when ON;
  present at baseline too (likely always-on clock modulated by activity) -> OOK is the scheme.
- Data: captures/avgdiff_{lo,vhf,uhf,uhfzoom}.npz, captures/waterfall.npz
- Report: report/phase1_report.html (+ fig1/2/3 png), published artifact.
- Scripts (scratchpad): wf_capture2.py, avg_diff.py, plot_report.py, build_report.py
