# Changelog

All notable changes to **02viz - Geospatial Visualization Studio** are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · versioning: [SemVer](https://semver.org/).

## [0.10.0] - 2026-06-16

- **Map diagrams can normalise their fields.** A new *Normalize* control rewrites each diagram field as an expression so fields on very different scales become comparable on every feature, instead of one big-number field swamping the rest. **Min–max (0–1)** is the safe default for pie/bar; **Z-score** standardises (great for bars; can be negative); **Log** compresses heavy tails. Each field's min/max/mean/std are computed from the (optionally selected) features and baked into the diagram's category expressions — **nothing is written to your data**. A live hint warns when Z-score is paired with a pie/stacked diagram (which can't draw negative angles).
- **Labels are now expression-driven.** Beyond a single field you can **round** numbers, add a **thousands separator**, stack a **second field on its own line** (a real newline via `char(10)`), add a **prefix/suffix** or units, change **case**, **word-wrap**, or type **any QGIS expression** in an advanced box that overrides the controls. A live **preview** shows the exact expression and a sample from the first feature, and numeric formatting is applied **only to numeric fields**, so a name on a second line is never wrapped in `round()`. Built on `QgsPalLayerSettings` expressions (`core/expressions.py`).
- **A built-in, offline user guide (❔ Guide).** A designed, self-contained HTML guide covers every surface — engines and the 17 chart types, animation, Explore, map-diagram **normalisation** (with worked examples), **copy-ready label-expression recipes**, the smart assistant, troubleshooting — plus **copy-ready prompts for an external AI assistant** (ChatGPT/Claude) for those who want extra help. No JavaScript, so it renders on every QGIS web backend and exports/opens anywhere. When opened from the dock it includes a personalised *“For your current layer”* section.
- **Smart suggestions (💡 Suggest), fully offline.** The dock reads the active layer's fields and picks the most insightful chart — a correlated-pair scatter with a trend line, a mean-by-category bar, a count bar or a histogram — configures the controls and renders it, telling you *why*. No account, no internet, no new dependencies (`core/assistant.py`).
- **Explore, levelled up.** The dashboard adds a collapsible **field-summary table** (type · missing % · distinct · range/top per field), an overall **completeness** KPI, a **normalised box plot** putting every numeric field on one 0–1 axis (the same comparability idea as the map-diagram normaliser), and deeper **insights** — dominant-category share, range, **skew with a log-transform hint**, **outliers** (1.5×IQR), near-constant and mostly-empty fields, and a couple more notable correlations.
- Verified end-to-end on **QGIS 3.44** and **QGIS 4**: expression labels evaluate to multi-line, formatted text; all four normalisation expressions parse and evaluate; the richer profile/dashboard build; the assistant and guide produce the expected output; and the dock wiring (label/diagram apply, Suggest, hints) was driven offscreen. No regression in the 48 static + 12 animated engine pages or the existing profile/dashboard tests.

## [0.9.2] - 2026-06-16

- **Plotly and Vega-Lite no longer leave a blank panel on QGIS builds without QtWebEngine.** When a QGIS build ships no QtWebEngine, the embedded panel falls back to the legacy QtWebKit viewer — and that old viewer cannot run the modern JavaScript (ES6+) that Plotly.js and Vega-Lite require, so their charts stayed blank in the dock even though they exported and opened correctly in a browser. ECharts and the matplotlib image engine were unaffected (they run on QtWebKit). The dock now detects the QtWebKit viewer and, for Plotly/Vega-Lite, shows a short explainer in the panel instead of a silent blank: your chart is still built — one click on **↗** opens it in your system browser, or use **Export HTML**. For a chart that renders inside the dock, switch to the **ECharts** engine, or install QtWebEngine for QGIS.
- Root-caused in real QGIS: under QtWebKit the engines fail with `ReferenceError: Can't find variable: Plotly` / `vega` (the bundles never parse), while ECharts renders normally; under QtWebEngine (QGIS 4 / Qt6) all engines render. Chart output, the engines themselves and exports are unchanged — this only affects what the embedded panel shows on a QtWebKit-only QGIS.

## [0.9.1] - 2026-06-16

- **Readable on QGIS 4 (Qt6).** The studio panel now pins its own light colours for every control, so it reads identically under any QGIS theme. On QGIS 4 the dark application palette bled into the parts the panel didn't explicitly colour: the drop-down lists rendered on a near-black background and the field labels and check-box text faded into the white cards. Combo pop-ups, line edits, spin boxes, the diagram field list, form labels, check boxes and tool-tips are now explicitly styled — white fields, dark text, teal selection — independent of the host palette. QGIS 3.x looked correct before (its palette is light) and is unchanged.
- The fix is purely the dock's stylesheet; the chart engines, rendering and exports are untouched. Re-verified end-to-end on **QGIS 4.0.2** and **QGIS 3.44**: all four engines render every supported type (ECharts 17, Plotly 17, Vega-Lite 14, matplotlib 11) plus the 12 animated pages, with zero JS exceptions in headless Chrome; the panel and an open drop-down were also grabbed under a simulated dark palette to confirm white fields and dark, legible text.

## [0.9.0] - 2026-06-16

- **Animated charts — a play axis.** Pick an *Animate by ▶* field (typically a year or sequence) and the chart plays through that field's values: a **bar-chart race**, **Gapminder-style bubbles**, or composition/trends unfolding over time. Available for **bar, line, area, scatter, bubble and pie** in the two interactive engines — **ECharts** (a timeline with auto-play) and **Plotly** (a slider with play / pause). A *Play speed* control sets the pace; the play axis greys out for engines and chart types that cannot animate (Vega-Lite, matplotlib, and types like box/heatmap/violin), consistent with the existing engine-first gating.
- **Things animate in place, not jump.** Every frame shares one axis: categories are merged into a stable, deterministically ordered union (a district keeps its slot and colour), the value axis is fixed to the global range across all frames, bubble sizes are scaled once globally so a value maps to the same radius throughout, and grouped series keep a consistent colour order. The current frame is shown as a subtitle (ECharts) and on the slider (Plotly).
- **Still linked to the map.** Animated bars and points carry their feature ids per frame, so clicking one during playback still selects the matching features on the canvas (cross-filter dimming pauses while animating, since each frame redraws the whole chart).
- **No new dependencies.** The frame builder is pure Python (`transform.build_frames` / `frame_groups` / `union_categories` / `align_values`); the vendored ECharts and Plotly engines do the rest entirely offline, and an animated chart still exports as one self-contained HTML file (with its play controls) like any other.
- Verified headless: real-QGIS checks for the frame builder (numeric/lexicographic frame ordering, union axis, global bounds, per-frame ids) and 12 animated engine×type pages, plus 12 animated pages in headless Chrome — auto-play stepping, slider/play controls present, zero JS exceptions; the bar-chart race, Gapminder bubbles, animated pie and lines eyeballed. No regression in the 48 static pages.

## [0.8.0] - 2026-06-13

- **One dock, three tabs** — the studio is now organised as **Charts · Map diagrams · Labels**, all sharing a single layer selector above the tabs. Same purpose throughout — turn a layer's data into an elegant visual — across three output surfaces.
- **Labels tab** — one click turns a field into well-placed, publication-grade labels with a preset (clean subtle-halo / strong halo / bold / plain), geometry-aware placement, built on native `QgsPalLayerSettings` (`core/labels.py`). Prints and exports like any QGIS labeling.
- **Embedded colour editor** — the palette is now an **inline swatch strip** in the Charts tab: click a swatch to recolour it, `+`/`−` to resize the palette, any edit switches to a custom palette — no modal dialog. Added a **chart-title override** field. (The old pop-up palette editor is gone.)
- **Optional advanced engine: matplotlib / seaborn** — a fourth engine renders the spec to **publication-grade static figures** (eleven chart types) and embeds them as a PNG in the same HTML shell, so the viewer and one-file export work unchanged. It appears in the engine picker; when its libraries are missing the dock offers a **one-click install** into the QGIS Python (`python -m pip install --user`, explicit consent only — `core/requirements.py`). The vendored JS engines stay zero-dependency and fully offline; this is the opt-in print/publication path (no chart→map interactivity on static images).
- **Zero2Visual** — the plugin's motto (“from zero to elegant visuals, fast”) now reads in the dock header and About box; the Hub name and "02viz" branding are unchanged.
- Verified headless: 86 checks on real QGIS Python (incl. the matplotlib engine across 11 types, on-canvas labels and the dependency detector) and 50 interactive chart pages in headless Chrome with zero JS exceptions; the matplotlib figures eyeballed.

## [0.7.0] - 2026-06-13

- **Map diagrams (on-canvas charts)** — a new *Map diagrams…* dialog draws native QGIS **pie / bar / stacked-bar / text** diagrams on every feature, directly on the map canvas, sized in millimetres and coloured with the studio palette. Built on `QgsDiagramRenderer`, so the diagrams print, export to print layouts and follow the layer like any other symbology. Numeric fields are pre-ticked (identifier columns skipped); attribute-only tables are detected and declined.
- **Custom colour palettes** — the *Colors* selector gains a **Custom…** entry that opens a swatch editor (add / remove / recolour via the system colour picker, seeded from the active palette). The result is written straight into the theme palette, so it recolours ECharts, Plotly and Vega-Lite identically — single charts and Explore dashboards alike.
- **Fixed: charts blank in the dock but fine on export** — the embedded viewer gave the chart container no definite height until after its first layout pass, so ECharts/Plotly/Vega measured a height of 0 and painted nothing (while export-to-browser worked). The chart box is now absolutely sized and re-fits once the view settles; the dock also nudges a resize on load. Added an **↗ open-in-browser** escape hatch and surfaced the active web backend (webengine / webkit) in the status line.
- **Engine-first workflow** — the dock now asks for the **Engine first**, then the chart **Type**, with unsupported types greyed out for the chosen renderer from the start.
- **Explore ignores identifier columns** — `fid`, `id`, `gid`, `oid`, `uuid`, `objectid`, `*_id`, and provider primary keys are no longer profiled into meaningless histograms or count bars on the dashboard.
- **Publication-grade visual polish** — one shared type system across all three engines, soft dashed horizontal gridlines (no vertical chart-junk), clean card-style tooltips, rounded bar tops and minimal value axes — output reads at Tableau quality.
- Verified headless: 73 checks on real QGIS Python (incl. the on-canvas diagram renderer and the identifier-column filter) and 50 chart pages in headless Chrome with zero JS exceptions; the polished output eyeballed across engines and themes.

## [0.6.0] - 2026-06-12

- **Six new advanced chart types** (17 total): **Mean ± σ band** (line with a shaded ±1 standard-deviation envelope), **Mean ± σ bars** (bars with std-dev whiskers), **Density (KDE)** (Gaussian kernel density curves, optionally one per group), **Violin plot** (mirrored KDE shapes with median dots), **Radar / spider** (multi-axis comparison with per-axis scaling) and **Pareto (80/20)** (descending bars plus a cumulative-share line on a second axis). All statistics — sample standard deviation, Silverman-bandwidth KDE, violin polygons, cumulative shares — are computed in pure Python and rendered by all three engines from one spec; only radar is greyed out for Vega-Lite (the grammar has no polar coordinates).
- **Color palettes** — a new *Colors* selector with 8 curated palettes (Vivid, Colorblind safe, Viridis, Sunset, Ocean, Earth, Berry, Grayscale print). The chosen palette overrides the theme palette identically in ECharts, Plotly and Vega-Lite, for single charts and Explore dashboards alike.
- Engine correctness fixes caught during visual verification: ECharts custom-series whiskers and violins now set explicit axis extents (custom series don't drive autoscaling, so +σ caps and violin tails were clipped) and error whiskers use a contrasting colour; Vega-Lite multi-series density sets `stack: null` (stacked-area zero-imputation turned smooth KDE curves into a sawtooth) and the violin ranged area dropped its `order` channel (it faceted every violin into degenerate per-row paths).
- Verified headless: 71 checks on real QGIS Python and 50 chart pages in headless Chrome with zero JS exceptions; every new engine×type screenshot eyeballed.

## [0.5.0] - 2026-06-12

- **Third engine: Vega-Lite** — vendored `vega` + `vega-lite` (BSD-3, compiled in the page, no vega-embed), fully offline. Renders 9 of the 11 chart types from the same spec contract (treemap/sunburst are not part of the Vega-Lite grammar), including layered box plots from precomputed quartiles and labelled heatmaps. Chart→map clicks and map→chart cross-filter dimming work exactly as in the other engines.
- **Engine-aware chart types** — engines declare what they can draw (`ChartEngine.supports`); the dock greys out unsupported types and jumps to the nearest supported one.
- **Heatmap label contrast fixed in all engines** — on sequential ramps, low-value cells are light, so white labels were invisible there; white is now used only on dark cells (both extremes on diverging ramps, upper end on sequential ones).

## [0.4.0] - 2026-06-12

- **Map → chart cross-filter**: selecting features on the canvas instantly dims every non-selected bar, slice and point — in the single chart and across all dashboard tiles — without a re-render (ECharts per-item opacity, Plotly native `selectedpoints`). A freshly rendered chart immediately reflects the current selection.
- **Crash-safe selection bridge**: chart clicks now reach QGIS through the page title (`titleChanged`) instead of `addToJavaScriptWindowObject`/`QWebChannel`, fixing an access-violation crash on QGIS builds that ship the legacy QtWebKit stack. One code path for WebKit and WebEngine; vendored `qwebchannel.js` removed.
- The chart→map bridge logic is now covered by headless real-QGIS tests (38 checks) and the cross-filter by the headless-Chrome harness (24 pages).

## [0.3.1] - 2026-06-12

- Package directory renamed from `02viz` to `zero2viz`: the QGIS Plugin Hub requires the zip's top-level directory to be a valid Python identifier (PEP 8), and the digit-first name was rejected at upload. The displayed plugin name, features and behaviour are unchanged.

## [0.3.0] - 2026-06-12

- ✨ **Explore**: one click profiles every field of a layer and builds a complete interactive dashboard — KPI cards, a count bar per categorical field, a histogram per numeric field, a Pearson correlation matrix (diverging colors), the strongest-relationship scatter with trend line, and plain-English insight chips. Exports as a single HTML file; every chart stays clickable (chart → map selection).
- Honest axes: bar, area and histogram value axes now always start at zero (a category could previously disappear).
- Heatmap polish: per-cell value labels with automatic contrast (white on intense cells) and a diverging red-teal ramp for correlation matrices in both engines.
- Human number formatting in titles and insights (219,250 instead of 2.192e+05).

## [0.2.0] - 2026-06-12

- Second rendering engine: Plotly.js (vendored, MIT) — switch engines per chart, same spec.
- Five new chart types: area (stackable), bubble, heatmap (matrix), treemap, sunburst — 11 total.
- Chart → map selection: clicking a bar, slice or point selects the matching features on the canvas (QtWebKit window-object bridge + QtWebEngine QWebChannel bridge).
- Live mode: optionally re-render the chart on every canvas selection change (with a loop guard for chart-driven selections).
- Group / Color-by field: grouped or stacked multi-series bars, multi-line, multi-area, colored scatter series.
- Data shaping: Top-N with "Other" collapse, value sorting, least-squares trend line, sqrt-scaled bubble sizes.
- Four themes (Studio Light, Ink Dark, Soft Pastel, Bold Print) applied consistently across both engines.
- Verified headless: 31 checks on real QGIS Python + all 22 engine×type combinations rendered in headless Chrome with zero JS errors.

## [0.1.0] - 2026-06-12

- Chart studio MVP: bar, line, scatter, histogram, pie/donut and box plot rendered by a vendored Apache ECharts engine (interactive HTML, fully offline).
- Data binding: any vector layer or table, selected-features-only mode, external CSV/XLSX/ODS tables via OGR.
- Pure-Python aggregation (count/sum/mean/median/min/max), histogram binning, box-plot quartiles.
- Embedded viewer with WebEngine → WebKit → system-browser fallback chain; one-file interactive HTML export.
