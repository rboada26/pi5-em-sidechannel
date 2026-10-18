# tempest-ddr — data-dependent memory-bus "antenna" test (Phase 1)

A deliberately simple TEMPEST transmitter for the Raspberry Pi 5, plus a
receiver-side averaging script. This is **Phase 1** of the cage experiment: before
trying to read anything off an LLM, establish that the board's own interconnect
radiates a *data-dependent* signal you can find and decode. It supplies a known,
periodic carrier on purpose, with the clocks pinned so DVFS is not a variable.

Lineage: Kuhn & Anderson, *Soft Tempest* (1998); Berke Durak's PCI/mem experiments
(lambda-diode, 1999), which drove a bus by writing alternating all-zeros
(`0x00000000`) and all-ones (`0xFFFFFFFF`) words so every data line swings
together. We do the same against LPDDR4X / the PCIe link to RP1 on the Pi 5, using
AArch64 non-temporal stores so the writes reach DRAM instead of parking in cache.

## Two modulation schemes — pick by your receiver
- **FSK (recommended if all you have is a spectrum analyzer).** The *data sets the
  emitted frequency*: a periodic memory-access "tick" repeats at a rate you choose,
  so it radiates a tone at that rate, and each data symbol picks a different tone.
  This is the loop-count/sleep idea — the loop timing is the data input that
  determines the frequency generated (Durak's CPU-loop tone; the "musical
  interference" memory-loop trick). A strong, frequency-agile tone is easy to read
  on a bare swept SA: set a span covering your tones, max-hold, watch which bin
  lights up. No near-field probe or SDR needed to get a first result.
- **OOK (needs a more sensitive receiver).** The data turns a loud DRAM burst on
  and off at a *fixed* carrier the hardware happens to emit. Decoding means finding
  that faint fixed line and averaging — easiest with an SDR or a near-field probe.

## What's here
- `tx_ddr.c` — the transmitter (runs on the Pi). `--fsk` keys the tone frequency
  (SA-friendly); default OOK keys a fixed carrier on/off; `--carrier` emits a
  continuous tone for tuning. Raises a GPIO frame trigger (BCM17).
- `sa_tinysa.py` — **tinySA Ultra+ (ZS-407) USB driver** (runs on your laptop).
  `ports`/`info`, `peak`, `sweep`→CSV, `watch`→time-log, `decode`→bits. Needs
  `pip install pyserial`. This is the receiver for this setup.
- `rx_sa.py` — offline analyzer for SA CSVs: `sweep` (data-dependent carrier via
  tx-on/off differencing), `zerospan`, `fsk`. `sa_tinysa.py sweep` output feeds it.
- `rx_average.py` — **SDR** decoder (IQ capture). Only if you later get an SDR.
- `Makefile` — native Pi build.

## tinySA Ultra+ (ZS-407) notes
- Connects by USB-C to your laptop as a serial port; `sa_tinysa.py` drives it. The
  cloud Claude session cannot reach it — capture runs on your machine.
- Lower limit 100 kHz; keep FSK tones in the low MHz (e.g. 1 MHz / 2 MHz).
- No external trigger input, so use long symbols + repeated frames and let
  `sa_tinysa.py decode` find the payload in the stream (see PATH A).

## Build (on the Pi)
```bash
sudo apt install build-essential libgpiod-dev
make
```
If you get `unknown type name 'gpiod_line_settings'`, your libgpiod is v1, not v2.
Pi OS Bookworm has v2. On older images, either upgrade, or install v2 from source.
Confirm your trigger pin's chip/line with `gpioinfo` (the RP1 bank is usually
`/dev/gpiochip0` on current firmware, but verify — on some images it's `gpiochip4`).

## Wiring the trigger
BCM17 goes high for each frame, BCM27 optionally toggles per symbol.
- **Spectrum analyzer (FSK):** you often need no trigger at all — read the tone by
  frequency. If your SA has an **external trigger input**, wire BCM17 to it to gate
  one sweep per frame (Pi GPIO is 3.3 V; check your SA's trigger threshold). Use
  BCM17 as the zero-span external trigger for the OOK path (A3).
- **SDR (OOK):** wire BCM17 to a logic input or log its monotonic-ns edges to a CSV
  for `rx_average.py --triglog`; or use `--autocorr` with no trigger at all.

Remember the cage rule from `CLAUDE.md`: only power (through the filter) and the
GPIO trigger line should cross the shield during a real capture.

# ============================================================================
# PATH A — tinySA Ultra+ (ZS-407) over USB  (the recommended path)
# ============================================================================
Two machines: the **Pi** (SSH in; runs `tx_ddr`) and your **laptop** (tinySA on
USB-C; runs `sa_tinysa.py`). Antenna/whip near the Pi board or its power lead.

One-time on the laptop:  `pip install pyserial numpy matplotlib`
Check the link:          `python3 sa_tinysa.py ports`  then  `... info`

## A1. Prove the board radiates at all (on/off differencing)
Pi:     `sudo ./tx_ddr --carrier`            (leave running)
Laptop: `python3 sa_tinysa.py sweep --start 100k --stop 30M --out on.csv`
Pi:     `touch /tmp/tx_stop`                 (stops the carrier)
Laptop: `python3 sa_tinysa.py sweep --start 100k --stop 30M --out off.csv`
        `python3 rx_sa.py sweep --trace on.csv --off off.csv --out sa_out`
Any line that appears only with tx running is board emission, not ambient. Repeat
across bands (0.1–30 MHz, 30–300 MHz, up toward the DDR/PCIe clocks) if nothing
shows at first. Note a frequency where tx clearly stands out.

## A2. FSK sanity check — watch the tone move
Pick two tones in the low MHz (tinySA floor is 100 kHz; give them room apart):
Pi:     `sudo ./tx_ddr --fsk 2M,2M --dwell 1000000 --bits 0 --reps 1 --cpu 2`
        (hack: hold one tone; or just run the real payload below and watch)
Laptop: `python3 sa_tinysa.py peak --start 500k --stop 3M`
Send the other tone and confirm the peak jumps. If the peak follows the data, the
loop timing is setting the frequency — Phase 1 is essentially proven.

## A3. Send a payload and decode it
No external trigger on the tinySA, so use long symbols and send the frame REPEATED,
then let `decode` find the payload in the captured stream.
Pi:     `sudo ./tx_ddr --fsk 1M,2M --dwell 1000 --bits 10110100 --reps 20 --cpu 2`
        (1000 ms/symbol, frame repeated 20× ≈ 160 s of airtime)
Laptop (start during transmission):
        `python3 sa_tinysa.py watch --start 500k --stop 3M --secs 60 --out fsk.csv`
        `python3 sa_tinysa.py decode fsk.csv --freqs 1M,2M --symbol-ms 1000 --nbits 8 --expect 10110100`
`decode` prints the whole decoded stream and finds `10110100` inside it with a bit
-error count. 0 errors = the memory loop's timing (the data) set the emitted tone,
recovered through the air. That is the Phase 1 result.

Tuning: if `decode` agreement is low, lengthen `--dwell` (slower symbols are easier
for a handheld to track), widen the tone spacing, move the whip closer, or narrow
the `watch` span around the two tones so each scan is faster (more samples/symbol).

## A4. (optional) OOK via long symbols
`sudo ./tx_ddr --bits 10110100 --symbol-ms 3 --reps 500 --cpu 2`, read with an SDR
(PATH B) or a zero-span-capable SA. The tinySA has no true zero-span time trace, so
FSK above is the better fit for it.

`rx_sa.py` reads most vendors' CSV and runs on the laptop. `sa_tinysa.py` needs
`pyserial`; `decode` needs only the stdlib.

# ============================================================================
# PATH B — with an SDR (OOK, higher fidelity)
# ============================================================================
Find `F` with `--carrier`, then:
```bash
sudo ./tx_ddr --bits 10110100 --reps 2000 --cpu 2 --stores 4096
hackrf_transfer -r cap.i8 -f <F_Hz> -s 8000000 -l 24 -g 20
python3 rx_average.py --iq cap.i8 --fmt int8 --fs 8e6 --fc <F_Hz> \
    --triglog trig.csv --t0 <ns_of_sample0> --nbits 8 --out rx_out
# or --autocorr instead of --triglog/--t0
```

## Knobs that matter
- **FSK:** `--fsk` tone list, `--dwell` ms per symbol, `--tick` words per period
  (smaller tick → higher reachable tone). Tones must be far enough apart for your
  SA's RBW to separate them.
- **OOK:** `--symbol-ms` sizes symbols to a target duration (use for a swept SA);
  `--stores` is the manual equivalent. `--gap` inserts idle between symbols.
- `--buf` must exceed L2/L3 (default 8 MiB) so stores hit DRAM. Shrink below cache
  size as a **control**: the DRAM signal should weaken markedly.

## Controls worth recording (for the writeup)
1. Buffer smaller than cache → signal should drop (proves it's DRAM traffic).
2. Scramble the payload to random bits → recovered sequence should match the scramble.
3. Idle baseline (don't run tx) → establishes the noise floor at your tones.
4. Move/rotate the antenna or probe → data-dependent peak should fall off.
