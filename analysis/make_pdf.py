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
    ("fig4_foil_shield.png",
     "Fig 4 - Aluminum-foil shield test. Paired measurement (same session, antenna fixed): the Pi was "
     "wrapped in aluminum foil (board insulated first; foil never touching pins) and the 255-295 MHz "
     "averaged on/off measurement repeated. The foil attenuates the carrier-on level by 5.3 dB at 263.4 "
     "MHz and 7.5 dB at 286.8 MHz. The activity-dependent detection weakens accordingly: at 263.4 MHz it "
     "falls below significance (t 6.6 -> 2.2); at 286.8 MHz it survives but is reduced (t 8.1 -> 5.0). "
     "A passive foil wrap can only attenuate a signal radiating into free space, so this independently "
     "confirms the emission is real board radiation. The shielding is partial - expected for a hand-wrapped, "
     "ungrounded foil with seams, and because the power cable penetrates the shield and can conduct/re-radiate "
     "the signal (the likely path for the surviving 286.8 MHz line)."),
    ("fig5_distance.png",
     "Fig 5 - Detection range vs. distance (antenna fully extended, near 1/4-wave for this band). "
     "Unshielded, the stronger 286.8 MHz line is readable out to ~30 cm and is gone by 40 cm; the weaker "
     "263.4 MHz line reaches ~10-15 cm. With the Pi wrapped in aluminum foil the signal is at the noise "
     "floor even at 4 cm - the foil cuts the readable range from ~30 cm to a couple of cm, a 7-10x "
     "reduction. Note the antenna matters: a collapsed whip could not read the signal at 10 cm at all, "
     "while the extended (resonant) whip read it to ~30 cm - so detection range is set as much by the "
     "receiver's antenna as by the source."),
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
    "near the board. Method: interleaved on/off sweeps (carrier toggled each round so ambient cancels),\n"
    "290 points/sweep, averaged, with a per-bin Welch t-test to separate real emission from ambient.\n\n"
    "Shielding: wrapping the Pi in aluminum foil (board insulated, foil clear of the pins) attenuates the\n"
    "emission by 5-7.5 dB and knocks out the 263.4 MHz detection, confirming the signal is genuinely\n"
    "radiated. The shield is partial - the power cable penetrates it and the 286.8 MHz line survives (t=5),\n"
    "pointing to the power lead as a leakage path and the next thing to measure.\n\n"
    "Detection range: with a resonant (fully extended) whip, the unshielded signal is readable to ~30 cm\n"
    "(286.8 MHz) and dies by 40 cm - a near-field-dominated emission. The foil wrap collapses this to a\n"
    "couple of cm (7-10x). The antenna matters as much as the source: a collapsed whip saw nothing at\n"
    "10 cm where the extended whip still read the signal clearly."
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

    # ---- distance / shielding tables page ----
    NOFOIL = [("~2 cm","original",6.6,8.1),("4 cm","collapsed",1.3,4.9),
              ("10 cm","collapsed",0.6,1.0),("10 cm (repos.)","collapsed",-1.4,0.3),
              ("10 cm","extended",5.6,4.3),("30 cm","extended",0.9,4.5),
              ("40 cm","extended",-0.2,0.9),("50 cm","extended",-0.2,0.1)]
    FOIL   = [("~2 cm","original",2.2,5.0),("4 cm","extended",-0.5,0.0),
              ("10 cm","extended",0.0,-0.4),("40 cm","extended",1.2,-0.3)]
    GREEN="#cdebc5"
    def add_table(fig, rect, rows):
        ax = fig.add_axes(rect); ax.axis("off")
        cols=["Distance","Antenna","263.4 MHz (t)","286.8 MHz (t)"]
        ct=[]; cc=[]
        for d_,a_,t1,t2 in rows:
            ct.append([d_,a_,"%.1f"%t1,"%.1f"%t2])
            cc.append(["#ffffff","#ffffff", GREEN if t1>=3 else "#ffffff",
                                            GREEN if t2>=3 else "#ffffff"])
        tb=ax.table(cellText=ct,colLabels=cols,cellColours=cc,
                    colColours=["#e6e6e6"]*4,loc="upper center",cellLoc="center")
        tb.auto_set_font_size(False); tb.set_fontsize(9); tb.scale(1,1.5)
    fig=plt.figure(figsize=(8.5,11)); axh=fig.add_axes([0,0,1,1]); axh.axis("off")
    axh.text(0.08,0.955,"Detection range vs. distance - shielded vs. not shielded",
             fontsize=15,fontweight="bold")
    axh.text(0.08,0.932,
             "t = Welch t-statistic = (mean level carrier-ON - mean level carrier-OFF) / noise spread of that\n"
             "difference. Higher t = more certain the signal is real, not noise. Green = detected (t >= 3,\n"
             "about 3 sigma). Antenna 'extended' = whip fully out (near 1/4-wave, resonant); 'collapsed' = stowed.",
             fontsize=9,color="#555",va="top",linespacing=1.5)
    axh.text(0.08,0.86,"Not shielded",fontsize=12,fontweight="bold")
    add_table(fig,[0.08,0.55,0.84,0.29],NOFOIL)
    axh.text(0.08,0.52,"Shielded (aluminum foil)",fontsize=12,fontweight="bold")
    add_table(fig,[0.08,0.34,0.84,0.165],FOIL)
    axh.text(0.08,0.285,
             "Max detection distance (extended whip):  not shielded ~10 cm (263.4 MHz) / ~30 cm (286.8 MHz);\n"
             "shielded < 4 cm for both lines. The antenna matters as much as the source - a collapsed whip\n"
             "barely read the signal even at 4 cm, where the extended whip read it clearly to ~30 cm.",
             fontsize=9.5,va="top",linespacing=1.5)
    pdf.savefig(fig); plt.close(fig)

    d = pdf.infodict(); d["Title"] = "Pi 5 EM Side-Channel - Phase 1"; d["Author"] = "R. Boada"

print("wrote", OUT)
