# 02viz architecture

```
zero2viz/               # package dir (display name stays "02viz")
  main_plugin.py        # QGIS lifecycle: toolbar, menu, dock toggle
  dialogs/
    dock.py             # StudioDockWidget: 3-tab dock (Charts/Diagrams/Labels) + spec assembly
    webview.py          # embedded viewer fallback chain + title listener
    bridge.py           # SelectionBridge: chart click → canvas selection
  core/
    datasource.py       # layer → row-aligned columns (+feature ids); OGR tables
    stats.py            # pure-Python aggregation / histogram / boxplot / Pearson / KDE
    transform.py        # pivot, heatmap matrix, tree, top-N, sort, trend, band, violin, pareto
    profile.py          # one-click layer profiling → dashboard tiles + insights (skips id columns)
    diagrams.py         # on-canvas QgsDiagramRenderer (pie/bar/stacked/text per feature)
    labels.py           # on-canvas QgsPalLayerSettings quick-label presets
    requirements.py     # optional-dependency detection + on-demand pip install
  engines/
    base.py             # ChartEngine contract (+available()), spec schema, themes, HTML shell
    echarts.py          # Apache ECharts engine (canvas)
    plotly.py           # Plotly.js engine (SVG)
    vegalite.py         # Vega-Lite engine (declarative grammar, canvas)
    mpl.py              # optional matplotlib/seaborn engine → static base64-PNG HTML
    dashboard.py        # profile → single-page dashboard (KPIs, insight chips, chart grid)
  web/
    echarts.min.js      # vendored, Apache-2.0
    plotly.min.js       # vendored, MIT
    vega.min.js         # vendored, BSD-3
    vega-lite.min.js    # vendored, BSD-3
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
   ``__o2vizSelect(ids)``, which encodes them into ``document.title``
   (``"o2viz-select:<ids>:<seq>"``). The dock listens to the view's
   ``titleChanged`` signal — identical API on QtWebKit and QtWebEngine —
   and ``SelectionBridge`` selects those features on the canvas.
   *Why not a JS↔Python object bridge?* QGIS's QtWebKit fork crashes
   (access violation in WebCore) when ``addToJavaScriptWindowObject`` is
   used, and ``QWebChannel`` only exists on WebEngine; the title is the
   one transport both stacks share. In a plain browser the title blips
   and clicks are otherwise inert.

## Hard rules

- **Relative imports only.** Kept as a hard convention from the era when
  the package was named `02viz` (digit-first, unimportable by literal
  statement; renamed to `zero2viz` because the QGIS Hub requires a PEP 8
  package name). Relative imports also survive any future rename.
- **No external Python dependencies.** Statistics are pure Python; chart
  libraries are vendored JS.
- **Engines never touch Qt.** `build_html(spec) -> str` keeps every engine
  testable on a bare Python interpreter and reusable for batch export.

## Engine roadmap

| Engine | Tech | Status |
|--------|------|--------|
| ECharts | vendored JS, canvas | ✅ v0.2.0 |
| Plotly.js | vendored JS, SVG | ✅ v0.2.0 |
| Vega-Lite | vendored JS (vega + vega-lite, no vega-embed), canvas | ✅ v0.5.0 — 14 of 17 types; treemap/sunburst (no grammar) and radar (no polar coords) are excluded via each engine's `supports` set, and the dock greys those types out |
| R / ggplot2 | subprocess bridge (optional, needs local R) | planned |

On-canvas diagrams (v0.7.0) are a separate path from the web engines:
`core/diagrams.py` attaches a `QgsSingleCategoryDiagramRenderer`
(pie/histogram/stacked-bar/text) straight to the layer, so they render,
print and export through QGIS itself — no web stack, no spec.

Vega-Lite gotcha: in a *layered* spec, a colour channel with `scale: null`
crashes the cross-layer scale merge (`Cannot read properties of null`).
Use filtered fixed-colour layers instead (see `_vl_heatmap`).

Map→chart cross-filter shipped in v0.4.0: the dock pushes
``__o2vizHighlight(ids)`` into the page (``run_js``: ``evaluateJavaScript``
on WebKit, ``runJavaScript`` on WebEngine — the QGIS→JS direction is safe
on both stacks) on every ``selectionChanged`` and on ``loadFinished``;
items carrying ``__ids`` dim unless selected (ECharts per-item opacity,
Plotly native ``selectedpoints``).

Planned next: small-multiples dashboards, custom spec editor for power
users, dashboard tile picker, SVG/PDF export.
