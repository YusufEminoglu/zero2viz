# 02viz architecture

```
02viz/
  main_plugin.py        # QGIS lifecycle: toolbar, menu, dock toggle
  dialogs/
    dock.py             # StudioDockWidget: builder UI + spec assembly
    webview.py          # embedded viewer fallback chain + bridge attachment
    bridge.py           # SelectionBridge: chart click → canvas selection
  core/
    datasource.py       # layer → row-aligned columns (+feature ids); OGR tables
    stats.py            # pure-Python aggregation / histogram / boxplot
    transform.py        # pivot, heatmap matrix, tree, top-N, sort, trend, bubble sizes
  engines/
    base.py             # ChartEngine contract, spec schema, themes, HTML shell
    echarts.py          # Apache ECharts engine (canvas)
    plotly.py           # Plotly.js engine (SVG)
  web/
    echarts.min.js      # vendored, Apache-2.0
    plotly.min.js       # vendored, MIT
    qwebchannel.js      # vendored, Qt BSD example — WebEngine bridge transport
```

## Flow

1. The dock builds a **spec** (plain dict — chart type, labels, plot-ready
   arrays *with feature ids*). All data shaping (aggregation, pivoting,
   binning, quartiles, top-N, trend) happens in `core/` with pure Python,
   so it is testable headless without Qt.
2. The selected **engine** turns the spec into one self-contained HTML
   document (vendored JS inlined → works offline, exports as a single file).
3. The HTML is written to a temp file and shown in the best available web
   widget: QtWebEngine → QtWebKit → system browser.
4. Charts are clickable: data items carry feature ids; the page calls
   ``o2vizBridge.select(ids)`` — injected directly on QtWebKit, resolved
   through a QWebChannel on QtWebEngine — and QGIS selects those features
   on the canvas. In a plain browser the bridge is absent and clicks are
   simply inert.

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
| Plotly.js | vendored JS, SVG | ✅ v0.2.0 |
| Vega-Lite | vendored JS, declarative grammar | planned |
| R / ggplot2 | subprocess bridge (optional, needs local R) | planned |

Planned next: map→chart cross-filter highlighting, small-multiples
dashboards, custom spec editor for power users, SVG/PDF export.
