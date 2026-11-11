# HackRF receiver pipeline

Receiver-side tools for the Pi 5 EM side-channel, using a **HackRF One** as the
SDR (the tinySA can detect the emission but is too slow to decode keying).

## Old-firmware note
These boards may carry very old firmware (e.g. 2015.07.2) that the stock
`hackrf_transfer` can't drive (it calls `hackrf_set_hw_sync_mode`, unsupported on
old firmware, and aborts). All scripts here instead drive `libhackrf` directly via
ctypes and simply skip that call, so they work **without a firmware update**.
Requires `hackrf` / `libhackrf0` installed (for the library and udev rules) and the
user in the `plugdev` group.

## Tools
| Script | What it does |
|--------|--------------|
| `hrf_capture.py` | Minimal RX smoke test — capture IQ at a frequency, confirm the device streams. |
| `hrf_detect.py` | Confirm the emission: K interleaved carrier ON/OFF rounds at 286.8 MHz, peak-in-window minus a reference band, Welch t-test. |
| `morse_decode.py` | Decode a Morse-keyed message. Runs `tx_ddr --morse` on the Pi, captures many repetitions, builds a band-power envelope, **coherently averages** (autocorrelation period + per-repetition alignment), thresholds, and Morse-decodes. |

## The SOS demo (end to end)
```bash
# just run the decoder; it drives the Pi transmitter itself:
python3 hackrf/morse_decode.py SOS 250 70
#   args: message, unit(dot) ms, capture seconds
```
The Pi keys its 286.8 MHz memory-bus emission in Morse ("SOS"); the HackRF records
~70 s; coherent averaging over the repeated message pulls the ~2 dB keying out of
the noise and recovers the text with zero errors.

Why averaging: a single symbol only modulates the band power by ~2-3 dB, below the
ambient fluctuation. Because the message repeats, folding many repetitions makes the
periodic keying reinforce while ambient/noise averages down — the same averaging
trick used to find the emission in the first place.

Longer `unit` (e.g. 250 ms) resolves the dashes/gaps more cleanly than short units.
