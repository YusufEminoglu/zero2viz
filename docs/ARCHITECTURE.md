# 02viz architecture

```
02viz/
  main_plugin.py        # QGIS lifecycle: toolbar, menu, dock toggle
  dialogs/
    dock.py             # StudioDockWidget: builder UI + spec assembly
    webview.py          # embedded viewer fallback chain
  core/
    datasource.py       # layer → row-aligned columns; external tables via OGR
    stats.py            # pure-Python aggregation / histogram / boxplot
  engines/
    base.py             # ChartEngine contract + spec schema
    echarts.py          # first engine: Apache ECharts, vendored, offline
  web/
    echarts.min.js      # vendored chart library (Apache-2.0)
```

## Flow

1. The dock builds a **spec** (plain dict — chart type, labels, plot-ready
   arrays). All data shaping (aggregation, binning, quartiles) happens in
   `core/` with pure Python, so it is testable headless without Qt.
2. The selected **engine** turns the spec into one self-contained HTML
   document (vendored JS inlined → works offline, exports as a single file).
3. The HTML is written to a temp file and shown in the best available web
   widget: QtWebEngine → QtWebKit → system browser.

## Hard rules

- **Relative imports only.** The package name `02viz` starts with a digit;
  `import 02viz` is a Python syntax error. QGIS loads plugins by string
  (`__import__("02viz")`), which works — but any absolute self-import
  would break the plugin.
- **No external Python dependencies.** Statistics are pure Python; chart
  libraries are vendored JS.
- **Engines never touch Qt.** `build_html(spec) -> str` keeps every engine
  testable on a bare Python interpreter and reusable for batch export.

## Engine roadmap

| Engine | Tech | Status |
|--------|------|--------|
| ECharts | vendored JS, canvas | ✅ v0.2.0 |
| Plotly.js | vendored JS | planned |
| Vega-Lite | vendored JS, declarative grammar | planned |
| R / ggplot2 | subprocess bridge (optional, needs local R) | planned |

Planned next: chart↔map linked selection via `QWebChannel`, multi-series,
color-by-category, small-multiples dashboards, PNG/SVG export server-side.
