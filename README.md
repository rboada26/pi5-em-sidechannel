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

See [`report/`](report/) for the figures.

## Layout

| Path | What it is |
|------|------------|
| `tempest-ddr/tx_ddr.c` | Transmitter that runs on the Pi. `--carrier` mode (continuous streaming writes to DRAM) is what produced the detected emission. |
| `tempest-ddr/sa_tinysa.py` | Driver for the tinySA Ultra+ spectrum analyzer (runs on the laptop; captures sweeps to CSV). |
| `tempest-ddr/rx_sa.py` | On/off differencing analysis for spectrum-analyzer CSV traces. |
| `tempest-ddr/rx_average.py` | SDR (IQ) averaging analysis — for the later, higher-fidelity path; not used in Phase 1. |
| `tempest-ddr/Makefile`, `README.md` | Build recipe and background. |
| `analysis/` | Scripts that produced the Phase 1 figures: averaged on/off differencing with a Welch t-test (`avg_diff.py`), the on/off waterfall capture (`wf_capture.py`), and figure/report generation. |
| `captures/` | Raw measurement data (`.csv`, `.npz`) and `NOTES.md`, the lab log. |
| `report/` | The three figures (PNG). |

## How the result was produced

1. Build the transmitter on the Pi: `cd tempest-ddr && make`.
2. Pin clocks: `sudo cpupower frequency-set -g performance`.
3. Run the carrier: `sudo ./tx_ddr --carrier` (writes `/tmp/tx_stop` to halt).
4. From the laptop, sweep with `sa_tinysa.py` while toggling the carrier on/off in
   interleaved rounds, then average and apply the per-bin t-test (`analysis/avg_diff.py`).

The analysis scripts expect this repository's directory layout and were run from the
laptop driving the analyzer over USB.
