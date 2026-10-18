#!/usr/bin/env python3
"""Basic PDF: summary + challenges page, then the three figures with captions."""
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.image as mpimg

R = "/home/robert/em-proj/report"
OUT = f"{R}/phase1_report.pdf"

figs = [
    ("fig1_averaging.png",
     "Fig 1 - Why averaging matters. Left: one carrier on/off pair gives a jagged +/-5-10 dB "
     "difference with an 'obvious' +10 dB spike at 18 MHz. Right: averaging 8 on + 8 off sweeps "
     "collapses the whole band to 0 +/- 1 dB. Ambient signals present in both states cancel; a true "
     "board emission would survive. Nothing does, so the 18 MHz line was ambient shortwave, not the Pi."),
    ("fig2_uhf_detection.png",
     "Fig 2 - The real emission, in UHF. Mean of 12 'carrier on' sweeps (red) vs 12 'off' (grey), "
     "255-295 MHz. Several peaks appear in BOTH states (ambient / always-on). Only at 263.4 and "
     "286.8 MHz does 'on' rise above 'off'. Lower panel: per-bin Welch t-statistic; shaded clusters "
     "clear t=4 and peak near t=10. Band-wide median |difference| is 0.84 dB, so these are 4-5 sigma "
     "detections - a genuine activity-dependent board emission."),
    ("fig3_waterfall.png",
     "Fig 3 - Watching it switch. Waterfall (frequency x time) around 286.8 MHz, memory loop on for "
     "the first 20 sweeps then off for the last 20. The vertical stripe is the emission; it is ~4.4 dB "
     "brighter while the loop runs (below the dashed line). The side panel tracks the level at 286.8 MHz "
     "per sweep: a clear step at the switch. The line is present at baseline too - likely an always-on "
     "clock that activity modulates, which is exactly the hook a side/covert channel would use."),
]

SUMMARY = (
    "Goal: show that the Raspberry Pi 5 radiates a measurable, data-dependent RF signal - the first\n"
    "('memory-bus antenna') milestone of the EM side-channel project - using a handheld spectrum analyzer\n"
    "with the board's memory loop toggled on and off.\n\n"
    "Result: YES - but not where we first looked. A single on/off spectrum pair pointed at ~18 MHz, but\n"
    "that was ambient shortwave. With proper averaging, the board's own activity-dependent emission shows\n"
    "up cleanly in UHF at 263.4 MHz and 286.8 MHz (detections at t = 8-10, i.e. 4-5 sigma, +3 to 4.7 dB\n"
    "above the idle floor). The emission is amplitude-modulated by activity, so on/off keying (OOK) at\n"
    "these carriers is the natural scheme going forward - not the low-MHz frequency-shift idea we started\n"
    "with (the memory 'tick' rate barely radiates on this hardware).\n\n"
    "Setup: Pi 5 (clocks pinned at 2.4 GHz) running tx_ddr --carrier; tinySA Ultra+ with a whip antenna\n"
    "near the board; no shield yet. Method: interleaved on/off sweeps (carrier toggled each round so\n"
    "ambient cancels), 290 points/sweep, averaged, with a per-bin Welch t-test to separate real emission\n"
    "from ambient."
)

CHALLENGES = (
    "Challenges faced and how we fixed them\n\n"
    "1. Ambient looked like signal. A single on/off pair showed a strong +10 dB line at 18 MHz. It was\n"
    "   ambient HF (the 15-20 MHz shortwave/ham band) in an unshielded room. Fix: average many on/off\n"
    "   cycles and apply a per-bin significance test; ambient cancels, real emission survives. Caught\n"
    "   before any conclusion left the bench.\n\n"
    "2. We were looking in the wrong band. The planned low-MHz memory-'tick' tone barely radiates on the\n"
    "   Pi 5 (short on-package LPDDR4X). Fix: sweep higher bands with the averaged method, which revealed\n"
    "   the true emission at 263.4 / 286.8 MHz (UHF switching/clock activity).\n\n"
    "3. Transmitter frequency-parser bug. tx_ddr's --fsk read SI suffixes wrong: '1M' became 1 Hz\n"
    "   instead of 1,000,000 Hz. Fix: added an SI-suffix parser (k/M/G) and rebuilt.\n\n"
    "4. Antenna swap didn't help. The HackRF ANT500 (75 MHz-1 GHz) performed worse than the stock whip\n"
    "   at our frequencies. Fix: kept the whip.\n\n"
    "5. Instrument / link friction. The tinySA serial port needed permissions each time it re-enumerated,\n"
    "   and the first sweep after a reconnect often returned empty; the Pi transmitter is root-owned and\n"
    "   holds the SSH channel open. Fix: warm-up/retry on empty scans, verify carrier state via pgrep\n"
    "   before each measurement, and fire-and-forget the remote transmitter."
)

with PdfPages(OUT) as pdf:
    # page 1: title + summary
    fig = plt.figure(figsize=(8.5, 11)); fig.subplots_adjust(left=0.08, right=0.95, top=0.95, bottom=0.06)
    ax = fig.add_axes([0,0,1,1]); ax.axis("off")
    ax.text(0.08, 0.955, "Pi 5 EM Side-Channel - Phase 1 Findings", fontsize=18, fontweight="bold")
    ax.text(0.08, 0.935, "Does the Raspberry Pi 5 radiate a data-dependent signal?  |  2026-10-17  |  "
            "R. Boada", fontsize=9, color="#555")
    ax.axhline(0.927, 0.08, 0.92, color="black", lw=1.2)
    ax.text(0.08, 0.90, SUMMARY, fontsize=9.5, va="top", family="DejaVu Sans", linespacing=1.5)
    ax.text(0.08, 0.50, CHALLENGES, fontsize=9.5, va="top", family="DejaVu Sans", linespacing=1.5)
    pdf.savefig(fig); plt.close(fig)
    # figure pages
    for img, cap in figs:
        fig = plt.figure(figsize=(8.5, 11))
        axi = fig.add_axes([0.06, 0.34, 0.88, 0.60]); axi.axis("off")
        axi.imshow(mpimg.imread(f"{R}/{img}"))
        axc = fig.add_axes([0.08, 0.06, 0.84, 0.24]); axc.axis("off")
        axc.text(0, 1, cap, fontsize=10, va="top", wrap=True, linespacing=1.5)
        pdf.savefig(fig); plt.close(fig)
    d = pdf.infodict(); d["Title"] = "Pi 5 EM Side-Channel - Phase 1"; d["Author"] = "R. Boada"

print("wrote", OUT)
