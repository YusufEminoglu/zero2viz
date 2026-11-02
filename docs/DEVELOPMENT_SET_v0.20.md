# 02Viz — Development Set for v0.20.0

**Goal: every chart tells the truth about the data, every export is what it
says it is, and the panel works at any dock width.**
Written 2026-11-02 from two audits in real QGIS 3.44 and 4.2 (chart
correctness and safety; first-minute UX, truth and demand). Exported pages
were checked in headless Chrome with the network blocked.

## 0. Baseline (2026-11-02)
- Hub downloads 10,627; `pf verify` green; Hub scan CLEAN.
- Measured clean: offline HTML exports (no request with the network
  blocked), NULL handling at extraction, selected-only mode and the 100k cap,
  unload, Turkish text, chart → map and map → chart linking, diagrams and
  labels, 20 chart types as advertised, spec build ≈0.5 s at 100k rows.
- Two real user issues on GitHub: #2 (layout, open since 2026-06-18,
  unanswered) and #1 (reverse axes / horizontal bars).

## 1. What the audits found
1. **Layout**: one row of eight buttons makes the panel 751–797 px wide, so a
   horizontal scrollbar appears at every dock width; Render, the chart and the
   status line sit far below the fold (GitHub #2).
2. **Charts that lie**: Plotly puts category codes ("30", "4", "100",
   "2024-03") on linear or date axes and drops "(null)"/"Other" bars;
   Top-N "Other" sums whatever aggregate is chosen (mean 10 shown as 150);
   dates become `PyQt5.QtCore.QDate(...)` strings and sort Jan, Oct, Feb;
   histogram bin labels collide (Vega-Lite merges bins, Plotly overlaps);
   aggregate "none" plots NULL as 0 and engines disagree on repeated X; the
   bar-chart race never re-sorts; Pareto with negatives passes 100%; booleans
   sum to 0; numeric frame labels sort "1", "10", "2".
3. **Injection**: the title (often a layer name) goes raw into `<title>` and an
   `alt=""`; JSON inside `<script>` is not escaped, so a value containing
   `</script>` blanks the page and a crafted name runs script (it can even
   select map features through the title bridge).
4. **Exports that are not what they say**: SVG and the "print-ready" PDF are
   bitmaps of the widget; on WebKit builds PNG/SVG/PDF save the "open in your
   browser" card; after a failed render or after opening the Guide the wrong
   page is exported and reported as success; the ECharts/Plotly toolbar
   download buttons do nothing.
5. **Hygiene**: a new temp HTML file per render (≥4.6 MB with Plotly) is never
   deleted; chart ids go stale after layer edits (a bar selects the wrong
   features); the matplotlib engine switches the process backend to Agg and
   changes global rcParams (affecting the QGIS console and other plugins) and
   blocked the GUI 185 s on a 100k-bar chart; the install command is built from
   `sys.executable` (qgis-bin.exe on Windows desktop).
6. **Smaller**: external CSV loads every column as text; only presets and the
   last folder survive a restart; contrast (white on #2a8f85 3.91:1,
   placeholder 2.88:1); checkbox indicators vanish under Fusion and paint dark
   under Night Mapping (TRAPS 3.7); garbled "Â·"; an empty "Spec JSON" label;
   Guide numbering and two false sentences.
7. **Copy**: "split any chart" (7 types can), "filter" (it dims), "matplotlib
   must be installed" (OSGeo4W ships it), "seventeen" chart types, "one of 16"
   plugins, 15 sibling links that all point to this repo; `tracker=` should be
   the GitHub repository where users actually report.
8. **Demand**: Hub search misses histogram, pie chart, scatter plot, box plot,
   heatmap, time series, bar chart race; users ask for charts coloured by the
   layer's symbology (GIS SE 447681, 343433, 342079; QGIS 4.2 added it to
   layout charts) and for horizontal/reversed axes (GitHub #1).

## 2. The set (acceptance = what a test asserts)
- **A. Layout.** No horizontal scroll at 350 px; exports in one menu; Render
  and the status line pinned at the bottom; advanced rows folded; the view
  scrolls to the chart after rendering; the first screen leads with layer and
  fields, engine choice under "Advanced". Test at 350 × 572.
- **B. True charts.** Category axes typed as categories (Plotly); Top-N
  "Other" computed with the chosen aggregate on the merged rows; dates as ISO
  strings and sorted as dates; histogram labels with a precision that keeps
  every bin distinct; aggregate "none" skips NULL Y and every engine draws
  repeated X the same way; the race re-sorts each frame; Pareto refuses
  negatives with a message; booleans counted; numeric frames sorted
  numerically. Horizontal bars and reversed axes (GitHub #1).
- **C. Safe pages.** Titles HTML-escaped everywhere; JSON in `<script>` with
  `</` escaped; the title bridge accepts only the plugin's own message shape.
- **D. Honest exports.** PNG/SVG/PDF disabled when the view shows anything but
  a rendered chart; SVG from each engine's own vector export (Plotly toImage
  svg, ECharts SVG renderer, Vega view.toSVG, matplotlib savefig svg), PDF from
  that SVG (vector), PNG at a size the user picks; toolbar download buttons
  saved through a `downloadRequested` handler. Engine pages expose
  `window.o2vizExport(format, width, height)` (contract below).
- **E. Hygiene.** One temp file per dock, removed on unload; edits/commits on
  the charted layer mark the chart stale and re-render; matplotlib through
  `Figure` + `FigureCanvasAgg` inside `rc_context` (no global state), large
  bar counts capped with a message; the install hint uses the QGIS Python
  executable.
- **F. Small.** CSV through the `delimitedtext` provider with type detection;
  the last setup restored on reopen; contrast ≥ 4.5:1; checkbox indicators
  visible under every built-in style and theme; the garbled and empty labels
  fixed; Guide numbering and claims true.
- **G. Layer colours.** A "Use layer colours" option: for a categorized or
  rule-based renderer, chart categories take the symbol colours (contract
  below).
- **T. Copy.** metadata (description true after D; tags add histogram, pie
  chart, scatter plot, box plot, heatmap, time series, bar chart race; tracker
  `https://github.com/YusufEminoglu/zero2viz/issues`; 0.20.0 line; no `%`),
  README (20 chart types, the real plugin count from `plugins.toml`, sibling
  links to the real repositories), CITATION, CHANGELOG 0.20.0.

## 3. Contracts between the parallel implementers
- **Exports**: every engine HTML page defines
  `window.o2vizExport = function (format, width, height)` returning a
  `Promise` that resolves to an SVG string for `"svg"` or a PNG data URL for
  `"png"`, at the given CSS pixel size. The dock calls it through the web
  view (WebEngine `runJavaScript` with a callback; WebKit
  `evaluateJavaScript` with a polling bridge) and writes the file; PDF is
  produced in Python from the SVG with `QSvgRenderer` → `QPdfWriter`.
- **Colours**: engines accept `options["category_colors"]` = `{category label
  (str): "#rrggbb"}`; when present, categories found in it use those colours,
  others keep the palette. The dock builds the map from the layer's renderer
  when the user ticks "Use layer colours".
- **Stale**: engines keep feature ids as today; the dock owns re-rendering.

## 4. Left out
- Several Y fields from wide tables (medium demand; next round).
- Atlas/report integration (QGIS 4 native charts cover static atlas output).
