# Pi 5 EM Side-Channel — Phase 1

Phase 1 of an EM (TEMPEST) side-channel study on the Raspberry Pi 5: establish that
the board's own memory-bus activity radiates a **data-dependent** RF signal that can
be measured from outside the board, before moving on to LLM-inference leakage.

## Result

With the Pi's clocks pinned and a memory loop toggled on/off, the board radiates an
**activity-dependent emission at 263.4 MHz and 286.8 MHz** — a few dB louder when the
memory bus is busy, quieter when idle (4–5σ after averaging). An initial single
on/off comparison pointed at ~18 MHz, but that turned out to be ambient shortwave; it
only disappeared once many on/off cycles were averaged with a per-bin significance
test. The low-MHz frequency-shift-keying (FSK) scheme did not radiate usably on this
hardware, so the practical scheme is on-off keying (OOK) at a fixed UHF carrier.

**Shielding & range:** wrapping the Pi in aluminum foil attenuates the emission by
5–7.5 dB and cuts the detection range from ~30 cm (unshielded, resonant whip) to a
couple of cm.

**Payload recovery (Phase 1 complete):** the Pi transmitted the message **"SOS" in
Morse code** through its 286.8 MHz emission (`tx_ddr --morse`), and a HackRF One
recovered it over the air with **zero errors** using coherent averaging of the
repeated message. See [`hackrf/`](hackrf/) and
[`report/sos_demo_report.pdf`](report/sos_demo_report.pdf).

See [`report/`](report/) for the figures and reports.

## Layout

| Path | What it is |
|------|------------|
| `tempest-ddr/tx_ddr.c` | Transmitter that runs on the Pi. `--carrier` mode (continuous streaming writes to DRAM) is what produced the detected emission. |
| `tempest-ddr/sa_tinysa.py` | Driver for the tinySA Ultra+ spectrum analyzer (runs on the laptop; captures sweeps to CSV). |
| `tempest-ddr/rx_sa.py` | On/off differencing analysis for spectrum-analyzer CSV traces. |
| `tempest-ddr/tx_ddr.c` | Also has `--morse TEXT` (OOK Morse keying of the carrier). |
| `tempest-ddr/rx_average.py` | SDR (IQ) averaging analysis. |
| `tempest-ddr/Makefile`, `README.md` | Build recipe and background. |
| `hackrf/` | HackRF One receiver pipeline: `hrf_capture.py` (RX smoke test), `hrf_detect.py` (interleaved on/off detection), `morse_decode.py` (coherent-averaging Morse decoder). Works around old HackRF firmware by driving `libhackrf` directly. |
| `analysis/` | Scripts that produced the figures: averaged on/off differencing with a Welch t-test (`avg_diff.py`), the waterfall capture (`wf_capture.py`), and figure/report generation (`make_pdf.py`). |
| `captures/` | Raw measurement data (`.csv`, `.npz`) and `NOTES.md`, the lab log. |
| `report/` | Figures (PNG) and report PDFs. |

## How the result was produced

1. Build the transmitter on the Pi: `cd tempest-ddr && make`.
2. Pin clocks: `sudo cpupower frequency-set -g performance`.
3. Run the carrier: `sudo ./tx_ddr --carrier` (writes `/tmp/tx_stop` to halt).
4. From the laptop, sweep with `sa_tinysa.py` while toggling the carrier on/off in
   interleaved rounds, then average and apply the per-bin t-test (`analysis/avg_diff.py`).

The analysis scripts expect this repository's directory layout and were run from the
laptop driving the analyzer over USB.
