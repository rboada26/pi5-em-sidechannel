#!/usr/bin/env python3
import base64, pathlib
R = pathlib.Path("/home/robert/em-proj/report")
def b64(name):
    return "data:image/png;base64," + base64.b64encode((R/name).read_bytes()).decode()
F1, F2, F3 = b64("fig1_averaging.png"), b64("fig2_uhf_detection.png"), b64("fig3_waterfall.png")

HTML = f"""<meta name="claude:viewport-fit-sides" content="cover">
<title>Pi 5 EM Emissions</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
/* Lab-memo layout: single reading column, full-width instrument figures, mono for data */
:root {{
  --bg:#f4f6f9; --surface:#ffffff; --fg:#161b26; --muted:#5a6675; --faint:#8793a3;
  --accent:#0b6e99; --signal:#d1242f; --border:#e3e8ef; --chip:#eef2f7;
  --ok:#1a7f52;
  --sans:"IBM Plex Sans",system-ui,sans-serif; --mono:"IBM Plex Mono",ui-monospace,monospace;
}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
  --bg:#0e1320; --surface:#151c2a; --fg:#e7ecf3; --muted:#9aa5b5; --faint:#6b7687;
  --accent:#49bde6; --signal:#ff6b6b; --border:#273246; --chip:#1b2434; --ok:#4ec28a;
  color-scheme:dark;
}}}}
:root[data-theme="dark"]{{
  --bg:#0e1320; --surface:#151c2a; --fg:#e7ecf3; --muted:#9aa5b5; --faint:#6b7687;
  --accent:#49bde6; --signal:#ff6b6b; --border:#273246; --chip:#1b2434; --ok:#4ec28a;
  color-scheme:dark;
}}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--fg);font-family:var(--sans);line-height:1.6;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:780px;margin:0 auto;
  padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));
  padding-block:clamp(28px,5vw,56px)}}
header{{border-bottom:2px solid var(--fg);padding-bottom:18px;margin-bottom:28px}}
.eyebrow{{font-family:var(--mono);font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--accent);font-weight:600;margin:0 0 10px}}
h1{{font-size:clamp(1.7rem,5vw,2.4rem);font-weight:700;line-height:1.1;margin:0 0 12px;
  text-wrap:balance;letter-spacing:-.01em}}
.sub{{color:var(--muted);font-size:1.02rem;margin:0;max-width:62ch}}
.meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}}
.meta span{{font-family:var(--mono);font-size:.74rem;background:var(--chip);color:var(--muted);
  border:1px solid var(--border);border-radius:5px;padding:4px 9px}}
h2{{font-size:1.18rem;font-weight:600;margin:38px 0 6px;letter-spacing:-.005em}}
h2 .n{{font-family:var(--mono);color:var(--accent);font-size:.8em;margin-right:.5em}}
p{{margin:10px 0}}
a{{color:var(--accent)}}
.lead{{font-size:1.05rem}}
.findings{{list-style:none;padding:0;margin:22px 0;display:grid;gap:12px}}
.findings li{{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--accent);
  border-radius:8px;padding:14px 16px}}
.findings li.neg{{border-left-color:var(--signal)}}
.findings li.pos{{border-left-color:var(--ok)}}
.findings b{{font-weight:600}}
.findings .k{{font-family:var(--mono);font-size:.78rem;color:var(--muted);display:block;
  letter-spacing:.06em;text-transform:uppercase;margin-bottom:3px}}
figure{{margin:22px 0 10px;background:var(--surface);border:1px solid var(--border);
  border-radius:10px;padding:12px;overflow-x:auto}}
figure img{{display:block;width:100%;min-width:560px;border-radius:4px}}
figcaption{{font-size:.9rem;color:var(--muted);margin-top:12px;padding:0 4px;line-height:1.55}}
figcaption b{{color:var(--fg);font-weight:600}}
code,.m{{font-family:var(--mono);font-size:.88em;background:var(--chip);padding:1px 5px;border-radius:4px}}
.note{{background:var(--chip);border:1px solid var(--border);border-radius:8px;padding:14px 16px;
  font-size:.92rem;color:var(--muted);margin:18px 0}}
.note b{{color:var(--fg)}}
hr{{border:none;border-top:1px solid var(--border);margin:34px 0}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0}}
@media(max-width:520px){{.grid2{{grid-template-columns:1fr}}}}
.spec{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 14px}}
.spec h3{{font-size:.76rem;font-family:var(--mono);text-transform:uppercase;letter-spacing:.1em;
  color:var(--faint);margin:0 0 8px;font-weight:600}}
.spec dl{{margin:0;display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:.88rem}}
.spec dt{{color:var(--muted)}}
.spec dd{{margin:0;font-family:var(--mono);font-size:.82rem;text-align:right}}
footer{{margin-top:40px;padding-top:16px;border-top:1px solid var(--border);
  font-size:.82rem;color:var(--faint)}}
</style>

<div class="wrap">
<header>
  <p class="eyebrow">Phase 1 · Microarch / Physical layer</p>
  <h1>Does the Raspberry&nbsp;Pi&nbsp;5 radiate a data-dependent signal?</h1>
  <p class="sub">A first bring-up with a handheld spectrum analyzer: can we detect, above a noisy
  unshielded room, an RF emission that switches with the board's memory activity — and at what frequency?</p>
  <div class="meta">
    <span>2026-10-17</span><span>R. Boada</span>
    <span>tinySA Ultra+ · whip · no shield</span>
  </div>
</header>

<p class="lead">Short answer: <b>yes — but not where we first looked.</b> A single on/off spectrum pair
pointed at ~18&nbsp;MHz, but that turned out to be ambient shortwave. With proper averaging the board's
own activity-dependent emission shows up cleanly in <b>UHF, at 263.4 and 286.8&nbsp;MHz</b>.</p>

<ul class="findings">
  <li class="neg"><span class="k">Cautionary result</span>
    The apparent <b>~18&nbsp;MHz</b> "emission" from single on/off differencing was <b>ambient HF</b>
    (the 15–20&nbsp;MHz shortwave/ham band), not the Pi. It vanishes under averaging.</li>
  <li class="pos"><span class="k">Primary result</span>
    Averaged on/off differencing reveals a genuine activity-dependent emission at
    <b>263.4&nbsp;MHz</b> and <b>286.8&nbsp;MHz</b> — detections at <b>t&nbsp;≈&nbsp;8–10</b> (4–5σ),
    reproducible across 12 on/off cycles.</li>
  <li class="pos"><span class="k">Method</span>
    The board-vs-ambient distinction is only visible with <b>averaging + significance testing</b>;
    it is the key technique for every later phase (and the argument for the shield).</li>
</ul>

<hr>

<h2><span class="n">01</span>Why a single measurement isn't enough</h2>
<p>The plan was to prove the board radiates by differencing the spectrum with the Pi's memory loop
running (<span class="m">./tx_ddr --carrier</span>) against idle. A single on/off pair showed strong
<span class="m">+10&nbsp;dB</span> "lines" near 18&nbsp;MHz — convincing until you repeat it. The room is
unshielded, and 15–20&nbsp;MHz is full of intermittent shortwave broadcast and amateur signals that a
whip antenna picks up. A single pair catches one of those in the "on" sweep and calls it signal.</p>
<figure>
  <img src="{F1}" alt="Left: noisy single-pair difference with a spurious peak at 18 MHz. Right: averaged difference, flat.">
  <figcaption><b>Fig 1.</b> Left — one on/off pair: a jagged ±5–10&nbsp;dB difference with an
  "obvious" +10&nbsp;dB spike at 18&nbsp;MHz. Right — averaging eight on and eight off sweeps (the carrier
  toggled between each) collapses the whole band to <b>0&nbsp;±&nbsp;1&nbsp;dB</b>. Ambient signals, present
  in both states, cancel; a true board emission would survive. Nothing does here, so the 18&nbsp;MHz line
  was ambient.</figcaption>
</figure>

<h2><span class="n">02</span>The real emission, in UHF</h2>
<p>Sweeping higher bands with the same averaged, carrier-toggled differencing and a per-bin Welch
<em>t</em>-test, two narrow lines stand out far above the noise — and only these two. They sit at
<b>263.4&nbsp;MHz</b> and <b>286.8&nbsp;MHz</b>, consistent with the Pi&nbsp;5's high-speed clock/switching
activity rather than the low-frequency memory "tick" we first aimed for.</p>
<figure>
  <img src="{F2}" alt="Averaged ON and OFF spectra over 255-295 MHz with t-statistic panel; significant clusters at 263.4 and 286.8 MHz.">
  <figcaption><b>Fig 2.</b> Mean of 12 "carrier on" sweeps (red) vs 12 "off" (grey), 255–295&nbsp;MHz.
  Several peaks appear in <em>both</em> states — those are ambient/always-on. Only at
  <b>263.4</b> and <b>286.8&nbsp;MHz</b> does "on" rise above "off". The lower panel is the per-bin
  <em>t</em>-statistic; shaded clusters clear <span class="m">t&nbsp;=&nbsp;4</span>, peaking near
  <b>t&nbsp;=&nbsp;10</b>. Band-wide median |difference| is 0.84&nbsp;dB, so these are 4–5σ detections.</figcaption>
</figure>

<h2><span class="n">03</span>Watching it switch — waterfall</h2>
<p>Zooming the analyzer onto the 286.8&nbsp;MHz line and sweeping repeatedly over time, with the memory
loop on for the first 20 sweeps and off for the last 20, shows the line brighten and dim in step with the
board's activity.</p>
<figure>
  <img src="{F3}" alt="Waterfall heatmap of 280-293 MHz over 40 sweeps; the 286.8 MHz stripe is brighter during the carrier-on half.">
  <figcaption><b>Fig 3.</b> Waterfall (frequency × time) around 286.8&nbsp;MHz. The vertical stripe is the
  emission; it is <b>~4.4&nbsp;dB brighter</b> during the "carrier on" half (below the dashed line) than when
  idle. The side panel tracks the level at 286.8&nbsp;MHz per sweep: a clear step at the switch. The line is
  present at baseline too — likely an always-on board clock that the memory activity <b>modulates</b>, which
  is exactly the hook a covert/side channel would use.</figcaption>
</figure>

<hr>

<h2><span class="n">04</span>What this means &amp; next steps</h2>
<p>Phase&nbsp;1's goal — show the board emits a measurable, data-dependent RF signal — is met, at
263.4 / 286.8&nbsp;MHz. The emission is amplitude-modulated by activity, so the natural modulation scheme
here is <b>on/off keying (OOK)</b> at those carriers, not the low-MHz frequency-shift scheme we started with
(the memory tick rate barely radiates on this hardware). The absolute levels are low (−72 to −77&nbsp;dBm at
a bare whip in open air), which is why averaging was essential.</p>
<div class="grid2">
  <div class="spec">
    <h3>Immediate next steps</h3>
    <dl>
      <dt>Shield</dt><dd>cuts ambient</dd>
      <dt>HackRF SDR</dt><dd>IQ + averaging</dd>
      <dt>OOK @287MHz</dt><dd>decode payload</dd>
      <dt>Power-line</dt><dd>measure channel</dd>
    </dl>
  </div>
  <div class="spec">
    <h3>Detections</h3>
    <dl>
      <dt>Line A</dt><dd>263.4 MHz</dd>
      <dt>Line B</dt><dd>286.8 MHz</dd>
      <dt>On−Off</dt><dd>+3–4.7 dB</dd>
      <dt>Signif.</dt><dd>t ≈ 8–10</dd>
    </dl>
  </div>
</div>
<div class="note"><b>Why a shield next.</b> The detections sit only ~4&nbsp;dB over the floor and the HF band
is swamped by ambient. A Faraday enclosure removes the ambient (turning single-shot measurement back into a
reliable method) and lets us measure how much signal escapes a real barrier — which becomes part of the
result, per the EMC-testing framing.</div>

<h2><span class="n">05</span>Setup &amp; honesty notes</h2>
<div class="grid2">
  <div class="spec">
    <h3>Equipment</h3>
    <dl>
      <dt>DUT</dt><dd>Pi 5, 4 GB</dd>
      <dt>Clocks</dt><dd>pinned 2.4 GHz</dd>
      <dt>Analyzer</dt><dd>tinySA Ultra+</dd>
      <dt>Antenna</dt><dd>whip, near board</dd>
      <dt>Shield</dt><dd>none yet</dd>
    </dl>
  </div>
  <div class="spec">
    <h3>Method</h3>
    <dl>
      <dt>Source</dt><dd>tx_ddr --carrier</dd>
      <dt>Scan</dt><dd>290 pts/sweep</dd>
      <dt>Avg</dt><dd>8–12 on/off</dd>
      <dt>Test</dt><dd>Welch t per bin</dd>
    </dl>
  </div>
</div>
<p style="font-size:.92rem;color:var(--muted)">Two corrections worth recording: (1) the initial 18&nbsp;MHz
result did not survive averaging and was ambient — flagged before any conclusion left the bench; (2) a bug in
the transmitter's frequency parser (SI suffixes like <span class="m">1M</span> were read as 1&nbsp;Hz) was
found and fixed. The HackRF antenna was tried on the analyzer and performed worse than the stock whip at these
frequencies, so the whip was kept.</p>

<footer>
  Agentic Security — microarchitectural/physical residue of AI agents. Phase 1 (memory-bus microbenchmark)
  of 3. Raw CSV/NPZ captures and analysis scripts archived alongside this report.
</footer>
</div>
"""
out = R/"phase1_report.html"
out.write_text(HTML)
print("wrote", out, "%.0f KB" % (len(HTML)/1024))
