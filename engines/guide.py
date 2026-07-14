# -*- coding: utf-8 -*-
"""The 02viz User Guide — one self-contained, offline HTML document.

A thorough, designed walk-through of every surface (Charts, Explore, Map
diagrams, Labels), the normalisation and label-expression recipes, the offline
smart assistant, and copy-ready prompts for using an external AI assistant.

Pure HTML/CSS, **no JavaScript** and no external assets, so it renders in the
embedded panel on every QGIS web backend (including the legacy QtWebKit) and
exports / opens in any browser. ``build_guide_html`` optionally embeds
per-layer recommendations from :mod:`core.assistant`.
"""
from __future__ import annotations

import html as _html

_CSS = """
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:#eef2f5;color:#22323a;
  font-family:"Segoe UI",system-ui,-apple-system,Roboto,Helvetica,Arial,sans-serif;
  font-size:15px;line-height:1.62}
a{color:#237a72;text-decoration:none}
a:hover{text-decoration:underline}
.layout{display:flex;max-width:1180px;margin:0 auto;align-items:flex-start}
nav{position:sticky;top:0;align-self:flex-start;width:232px;flex:0 0 232px;
  padding:26px 14px 26px 22px;max-height:100vh;overflow:auto}
nav .brand{font-size:22px;font-weight:800;color:#16323f;letter-spacing:.3px}
nav .brand b{color:#2a8f85}
nav .tag{color:#6b7a82;font-size:12px;margin:2px 0 16px}
nav a{display:block;color:#46555d;padding:5px 10px;border-radius:7px;font-size:13.5px}
nav a:hover{background:#e2e9ed;text-decoration:none}
main{flex:1;background:#ffffff;border-left:1px solid #dde4e8;min-height:100vh;
  padding:30px 40px 64px}
header.hero{border-bottom:1px solid #e7ecef;padding-bottom:18px;margin-bottom:8px}
header.hero h1{margin:0;font-size:30px;color:#16323f}
header.hero h1 b{color:#2a8f85}
header.hero p{margin:8px 0 0;color:#5b6b73;font-size:15.5px}
section{padding:22px 0;border-bottom:1px solid #eef1f3}
section:last-child{border-bottom:0}
h2{font-size:21px;color:#16323f;margin:0 0 6px;scroll-margin-top:14px}
h2 .n{color:#2a8f85;font-weight:800;margin-right:8px}
h3{font-size:16px;color:#1f4a45;margin:18px 0 4px}
p{margin:8px 0}
ul,ol{margin:8px 0;padding-left:22px}
li{margin:4px 0}
code{background:#f0f4f6;border:1px solid #e0e7ea;border-radius:5px;
  padding:1px 6px;font-family:"Cascadia Code",Consolas,monospace;font-size:13px;
  color:#0f5b53}
pre{background:#0f242b;color:#d6f0ea;border-radius:9px;padding:13px 15px;
  overflow:auto;font-family:"Cascadia Code",Consolas,monospace;font-size:12.5px;
  line-height:1.5}
pre b{color:#7fd1c5;font-weight:600}
.card{background:#fbfdfe;border:1px solid #e3e9ec;border-radius:11px;
  padding:14px 18px;margin:12px 0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.note{border-left:4px solid #2a8f85;background:#f1faf8;padding:10px 14px;
  border-radius:0 9px 9px 0;margin:12px 0}
.warn{border-left:4px solid #e0a346;background:#fdf6ea;padding:10px 14px;
  border-radius:0 9px 9px 0;margin:12px 0}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}
th{text-align:left;background:#f3f6f8;color:#3a4a52;padding:8px 11px;
  border:1px solid #e3e9ec;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
td{padding:8px 11px;border:1px solid #e9eef1;vertical-align:top}
td code{white-space:nowrap}
.pill{display:inline-block;font-size:11px;font-weight:700;padding:2px 9px;
  border-radius:999px;margin-right:6px}
.pill.chart{background:rgba(42,143,133,.16);color:#207168}
.pill.diagram{background:rgba(244,162,97,.2);color:#b06a1c}
.pill.label{background:rgba(131,56,236,.14);color:#6b2fc0}
.pill.explore{background:rgba(33,122,114,.14);color:#16323f}
.sug{border:1px solid #e3e9ec;border-radius:10px;padding:12px 15px;margin:10px 0;
  background:#fbfdfe}
.sug h4{margin:0 0 4px;font-size:15px;color:#16323f}
.sug .why{color:#52616a;font-size:13.5px;margin:3px 0}
.sug .how{color:#207168;font-size:13px;margin:5px 0 0}
footer{color:#8194a0;font-size:12.5px;text-align:center;padding-top:22px}
"""

# (id, label) for the sidebar table of contents
_TOC = (
    ("start", "Quick start"),
    ("data", "Choosing data"),
    ("charts", "Charts"),
    ("explore", "Explore (dashboard)"),
    ("diagrams", "Map diagrams"),
    ("normalise", "Normalising diagrams"),
    ("labels", "Labels & expressions"),
    ("assistant", "Smart suggestions"),
    ("ai", "Use an AI assistant"),
    ("trouble", "Troubleshooting"),
)


def _suggestion_cards(suggestions: list) -> str:
    if not suggestions:
        return ""
    cards = []
    for s in suggestions:
        surface = _html.escape(str(s.get("surface", "")))
        cards.append(
            f'<div class="sug"><span class="pill {surface}">{surface}</span>'
            f'<h4 style="display:inline">{_html.escape(str(s.get("title", "")))}</h4>'
            f'<div class="why">{_html.escape(str(s.get("why", "")))}</div>'
            f'<div class="how">{_html.escape(str(s.get("how", "")))}</div></div>')
    return (
        '<section id="foryou"><h2><span class="n">★</span>For your current layer'
        '</h2><p>02viz looked at the active layer\'s fields and suggests:</p>'
        + "".join(cards) + "</section>")


def build_guide_html(suggestions: list | None = None,
                     layer_name: str = "") -> str:
    """Return the complete guide as one HTML string. When ``suggestions`` is
    given (from :func:`core.assistant.suggestions`) a personalised section for
    the active layer is inserted near the top."""
    toc = "".join(f'<a href="#{i}">{_html.escape(lbl)}</a>' for i, lbl in _TOC)
    foryou = _suggestion_cards(suggestions or [])
    foryou_link = ('<a href="#foryou"><b>★ For your current layer</b></a>'
                   if foryou else "")
    subtitle = ("How every part works, and how to get a great result fast."
                if not layer_name
                else f"Tuned to the layer “{_html.escape(layer_name)}”.")

    head = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>02viz — User Guide</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_CSS}</style></head>
<body><div class="layout">
<nav>
  <div class="brand"><b>02</b>viz</div>
  <div class="tag">Geospatial Visualization Studio</div>
  {foryou_link}
  {toc}
</nav>
<main>
<header class="hero">
  <h1><b>02</b>viz — User Guide</h1>
  <p>{subtitle}</p>
</header>

{foryou}
"""
    # The large static body is a plain (non-formatted) string constant so the
    # security scanner never mistakes its prose ("…selects…", "…from…") for a
    # formatted SQL query (Bandit B608). Only the small head above interpolates.
    return head + _BODY


_BODY = """
<section id="start"><h2><span class="n">1</span>Quick start</h2>
<ol>
  <li>Open the studio from the <b>02viz</b> toolbar button (the dock opens on the right).</li>
  <li>In the <b>Data</b> card, pick a vector layer — or <b>Load external table…</b> for a CSV/XLSX.</li>
  <li>On the <b>Charts</b> tab choose an <b>Engine</b>, a chart <b>Type</b>, set <b>X</b>/<b>Y</b> and hit <b>Render chart</b>.</li>
  <li>Not sure what to make? Click <b>💡 Suggest</b> for an instant chart, or <b>✨ Explore layer</b> for a full dashboard.</li>
</ol>
<div class="note">Everything is offline. Charts export as a single self-contained
HTML file (<b>Export HTML…</b>), and clicking a bar/point selects those features
on the map.</div>
</section>

<section id="data"><h2><span class="n">2</span>Choosing data</h2>
<p>The <b>Data</b> card sits above the tabs and feeds all three surfaces.</p>
<ul>
  <li><b>Layer</b> — any vector layer, spatial or attribute-only.</li>
  <li><b>Only selected features</b> — chart/diagram/label just the current selection.</li>
  <li><b>Live: redraw on selection</b> — re-render automatically as the map selection changes.</li>
  <li><b>Load external table…</b> — opens a CSV/XLSX/ODS/GeoPackage table and adds it to the layer list.</li>
</ul>
</section>

<section id="charts"><h2><span class="n">3</span>Charts</h2>
<p>Pick the <b>Engine</b> first — it decides which types are drawable (unsupported
types grey out) — then the <b>Type</b>.</p>
<table><tr><th>Engine</th><th>Suitable for</th><th>Notes</th></tr>
<tr><td>ECharts</td><td>Everyday interactive charts</td><td>All 17 types; runs in the dock on every QGIS build; can animate.</td></tr>
<tr><td>Plotly.js</td><td>Rich hover &amp; zoom</td><td>All 17 types; can animate. Needs a modern web view (see Troubleshooting).</td></tr>
<tr><td>Vega-Lite</td><td>Clean grammar-of-graphics</td><td>14 types. Needs a modern web view.</td></tr>
<tr><td>matplotlib / seaborn</td><td>Publication-grade static figures</td><td>Installs on demand; image output (no click-to-select).</td></tr></table>

<h3>The 17 chart types</h3>
<table><tr><th>Type</th><th>Reach for it when…</th></tr>
<tr><td>Bar</td><td>Compare a measure across categories (counts or an aggregate).</td></tr>
<tr><td>Line / Area</td><td>A measure along an ordered axis; area to stress volume / stacking.</td></tr>
<tr><td>Scatter</td><td>Relationship between two numbers (add a <b>Trend line</b>).</td></tr>
<tr><td>Bubble</td><td>Scatter with a third number as the dot size.</td></tr>
<tr><td>Histogram</td><td>Shape and spread of one numeric field (set <b>Bins</b>).</td></tr>
<tr><td>Pie / donut</td><td>Parts of a whole for a single category (use <b>Top N</b>).</td></tr>
<tr><td>Box</td><td>Median, quartiles and outliers, optionally per group.</td></tr>
<tr><td>Heatmap</td><td>A value across two categorical axes (a matrix).</td></tr>
<tr><td>Treemap / Sunburst</td><td>Hierarchical parts of a whole (group → sub-group).</td></tr>
<tr><td>Mean ± σ band / bars</td><td>Average with a one-standard-deviation envelope or whiskers.</td></tr>
<tr><td>Density (KDE)</td><td>Smooth distribution, one curve per group.</td></tr>
<tr><td>Violin</td><td>Distribution shape with the median marked.</td></tr>
<tr><td>Radar</td><td>Compare several measures on one figure (≥ 3 axes).</td></tr>
<tr><td>Pareto</td><td>Sorted bars + cumulative-share line (the 80/20 view).</td></tr></table>

<h3>Shaping controls</h3>
<ul>
  <li><b>Aggregate</b> — none / count / sum / mean / median / min / max for the Y measure.</li>
  <li><b>Group / Color</b> — split into one coloured series per value.</li>
  <li><b>Top N</b> + <b>Sort</b> — keep the N biggest categories (rest → “Other”), order by value.</li>
  <li><b>Trend line</b> — least-squares fit on scatter/bubble.</li>
  <li><b>Animate by ▶</b> — turn a year/sequence field into a play axis: a bar-chart
      race or Gapminder-style bubbles (ECharts &amp; Plotly; bar·line·area·scatter·bubble·pie).
      Axes and colours stay fixed across frames; set the pace with <b>Play speed</b>.</li>
</ul>

<h3>Reference &amp; statistics overlays</h3>
<p>On <b>bar, line, area, scatter</b> and <b>bubble</b> charts the <b>Reference:</b> row
   draws guide lines and shaded bands on the value axis, computed from the plotted numbers:</p>
<ul>
  <li><b>Mean</b> / <b>Median</b> — a dashed line at the average / middle value.</li>
  <li><b>±1σ</b> — a shaded band one standard deviation either side of the mean.</li>
  <li><b>IQR</b> — a shaded band across the inter-quartile range (Q1–Q3).</li>
  <li><b>Target…</b> — type any number to draw your own threshold line.</li>
</ul>
<p>Turn on any combination; every engine draws them the same way and they export with the
   chart. Overlays are hidden while a chart is animating.</p>

<h3>Colours &amp; interactivity</h3>
<ul>
  <li><b>Theme</b> + <b>Colors</b> — eight palettes, or click a swatch / <b>Custom…</b>
      to edit your own; applied identically across every engine.</li>
  <li><b>Click selects on map</b> — clicking a bar/slice/point selects those features
      in QGIS; selecting on the canvas dims the non-selected chart items (cross-filter).</li>
  <li><b>Export HTML…</b> writes the chart as one portable file; <b>↗</b> opens it in your browser.</li>
</ul>
</section>

<section id="custom"><h2><span class="n">4</span>Custom specs and exports</h2>
<p>When the engine is <b>Vega-Lite</b>, enable <b>Custom Vega-Lite spec</b> to edit the generated JSON. Press <b>Render chart</b> to validate it and render it with the bundled offline Vega runtime. Parse errors remain in the status panel.</p>
<p>The current data is injected as the named offline dataset <code>o2viz</code>. Keep the generated <code>__ids</code> values in your rows when you want chart clicks to select map features.</p>
<ul><li><b>Export HTML</b> saves the complete offline page.</li><li><b>Export SVG</b> and <b>Export PNG</b> use the active rendered view where the engine supports it.</li><li><b>Export PDF</b> uses QGIS print output and does not require a browser or network.</li></ul>
</section>

<section id="tiles"><h2><span class="n">5</span>Explore tile picker</h2>
<p>Before opening Explore, use the checkable tile picker to choose KPI row, field table, count bars, histograms, correlation matrix, scatter with trend, normalised box plot and insights. The default keeps the complete dashboard output.</p>
</section>
<section id="explore"><h2><span class="n">4</span>Explore — one-click dashboard</h2>
<p><b>✨ Explore layer</b> profiles every field and builds a full interactive page:</p>
<ul>
  <li><b>KPI cards</b> — rows, fields, numeric/categorical counts and overall completeness.</li>
  <li><b>Field summary table</b> — type, missing %, distinct count and a min…mean…max
      (or top value) for each field, collapsible.</li>
  <li><b>Charts</b> — count bars for categories, histograms for numbers, a
      <b>normalised box plot</b> putting every numeric field on one 0–1 axis, a Pearson
      <b>correlation matrix</b> and the strongest-pair scatter with a trend line.</li>
  <li><b>Insights</b> — plain-English notes on the dominant category, range, skew
      (with a log-transform hint), outliers, near-constant and mostly-empty fields,
      and notable correlations.</li>
</ul>
<p>Identifier columns (<code>fid</code>, <code>id</code>, <code>uuid</code>, primary keys…) are skipped — they carry no analytical meaning.</p>
</section>

<section id="diagrams"><h2><span class="n">5</span>Map diagrams (on the canvas)</h2>
<p>The <b>Map diagrams</b> tab draws a small <b>pie / bar / stacked / text</b> diagram on
<i>every feature</i>, directly on the map, using native QGIS rendering — so it prints,
exports to layouts and follows the layer like any symbology.</p>
<ol>
  <li>Tick one or more <b>numeric fields</b> (they become slices / bars).</li>
  <li>Pick the diagram <b>Type</b> and a <b>Size (mm)</b>.</li>
  <li>Choose a <b>Normalize</b> mode (next section), then <b>Apply to layer</b>.</li>
</ol>
</section>

<section id="normalise"><h2><span class="n">6</span>Normalising diagrams — why it matters</h2>
<p>Put two fields on very different scales into one pie or bar — say
<code>population</code> (0–500,000) and <code>area_km2</code> (0–40) — and the big-number
field swamps the small one: the slice or bar for <code>area_km2</code> is invisible and
the comparison is meaningless. <b>Normalising</b> rewrites each field as an expression so
the values become comparable.</p>
<table><tr><th>Mode</th><th>What it does</th><th>Use it for</th></tr>
<tr><td>None</td><td>Raw attribute values.</td><td>Fields already on the same scale / units.</td></tr>
<tr><td>Min–max (0–1)</td><td><code>(v − min) / (max − min)</code></td><td>The safe default — every field spans 0–1; great for pie &amp; bar.</td></tr>
<tr><td>Z-score</td><td><code>(v − mean) / std</code></td><td>“How far from average”; suits bars (can be negative — avoid for pie).</td></tr>
<tr><td>Log</td><td><code>ln(v − min + 1)</code></td><td>Heavy-tailed / skewed fields where a few features dominate.</td></tr></table>
<div class="note">02viz computes each field's min / max / mean / std from the (optionally
selected) features and bakes them into the diagram's category expressions — no new
columns are written to your data.</div>
<div class="warn">Z-score can produce negative values, which a pie can't draw as an
angle. For pie / stacked diagrams prefer <b>Min–max</b> or <b>Log</b>.</div>
</section>

<section id="labels"><h2><span class="n">7</span>Labels &amp; expressions</h2>
<p>The <b>Labels</b> tab turns a field into well-placed, publication-grade labels with a
style preset (clean halo / strong halo / bold / plain). Beyond a single field you can
<b>format</b> and <b>compose</b> the text without leaving the dock:</p>
<ul>
  <li><b>Second line field</b> — stacks a second field below the first (a real newline).</li>
  <li><b>Decimals</b> — round numbers, e.g. <code>3.14159 → 3.1</code>.</li>
  <li><b>Thousands separator</b> — <code>1234567 → 1,234,567</code>.</li>
  <li><b>Prefix / Suffix</b> — units or symbols, e.g. <code>€</code> … <code> m²</code>.</li>
  <li><b>Case</b> — UPPER / lower / Title.</li>
  <li><b>Wrap at N characters</b> — break long names onto multiple lines.</li>
  <li><b>Advanced expression</b> — type any QGIS expression; it overrides the controls.
      A live preview shows the exact expression being applied.</li>
</ul>
<h3>Copy-ready expression recipes</h3>
<p>Paste any of these into <b>Advanced expression</b>:</p>
<pre>round(<b>"price"</b>, 1)                       <b>// 3.14159 → 3.1</b>
format_number(<b>"population"</b>, 0)            <b>// 1234567 → 1,234,567</b>
concat(<b>"name"</b>, char(10), <b>"type"</b>)         <b>// name, then type on a new line</b>
concat(<b>"name"</b>, ': ', round(<b>"value"</b>, 1))    <b>// District: 12.4</b>
concat('€ ', format_number(<b>"rent"</b>, 0))      <b>// € 14,500</b>
upper(left(<b>"code"</b>, 3))                    <b>// first 3 letters, UPPERCASE</b>
wordwrap(<b>"long_name"</b>, 16)                 <b>// wrap every ~16 characters</b></pre>
<div class="note"><code>char(10)</code> inserts a line break; <code>round()</code> and
<code>format_number()</code> handle decimals; <code>concat()</code> joins text and numbers.</div>
</section>

<section id="assistant"><h2><span class="n">8</span>Smart suggestions (offline)</h2>
<p>02viz includes a built-in, fully offline assistant — no account, no internet.
It reads the active layer's fields and proposes concrete next steps:</p>
<ul>
  <li><b>💡 Suggest</b> (Charts tab) picks the most insightful chart for your fields —
      a correlated-pair scatter, a mean-by-category bar, a count bar or a histogram —
      configures the controls and renders it, telling you <i>why</i>.</li>
  <li>The <b>★ For your current layer</b> panel (top of this guide, when opened from the
      dock) lists recommendations for charts, map-diagram normalisation and labels.</li>
</ul>
</section>

<section id="ai"><h2><span class="n">9</span>Use an AI assistant (optional)</h2>
<p>02viz never sends your data anywhere. If you'd like extra help, copy one of these
prompts into ChatGPT, Claude or any LLM, paste in your field names, and bring the
answer back (for example into the <b>Advanced expression</b> box).</p>
<h3>Recommend a chart</h3>
<pre>I'm using the 02viz QGIS plugin. My layer's fields are:
<b>&lt;paste field names and a few example rows&gt;</b>
Which 02viz chart type and which X / Y / Group / Aggregate
settings would show most clearly the main story? Explain why in 2 lines.</pre>
<h3>Write a label expression</h3>
<pre>Write a single QGIS label expression (functions: concat, round,
format_number, char(10), upper, title, wordwrap) that shows:
<b>&lt;describe the label you want, e.g. "NAME on line 1, population
rounded with thousands separators on line 2"&gt;</b>
Return only the expression.</pre>
<h3>Pick a normalisation</h3>
<pre>In 02viz map diagrams I'm comparing these numeric fields on each
feature: <b>&lt;fields and their rough ranges&gt;</b>. Should I use
Min–max, Z-score or Log normalisation, and why? One short paragraph.</pre>
</section>

<section id="trouble"><h2><span class="n">10</span>Troubleshooting</h2>
<table><tr><th>Symptom</th><th>Fix</th></tr>
<tr><td>Embedded panel is blank with Plotly or Vega-Lite</td>
<td>That QGIS build has only the legacy QtWebKit view, which can't run those engines.
Click <b>↗</b> to open in your browser, switch the engine to <b>ECharts</b> (renders in the
dock everywhere), or install QtWebEngine for QGIS.</td></tr>
<tr><td>Drop-downs or labels look dark / unreadable</td>
<td>Fixed in 0.9.1 — the panel pins its own light colours under any QGIS theme. Update 02viz.</td></tr>
<tr><td>“Aggregation needs a Y field”</td>
<td>Pick a numeric <b>Y</b> field, or set <b>Aggregate = count</b> (which ignores Y).</td></tr>
<tr><td>matplotlib engine asks to install</td>
<td>It's the optional publication-grade engine; click to install into the QGIS Python, or use a vendored engine (ECharts/Plotly/Vega-Lite).</td></tr>
<tr><td>Pie slices look wrong after normalising</td>
<td>Z-score can be negative — use <b>Min–max</b> or <b>Log</b> for pie / stacked diagrams.</td></tr></table>
</section>

<footer>02viz · Zero2Visual — from zero to elegant visuals.
Everything in this guide works offline.</footer>
</main></div></body></html>
"""
