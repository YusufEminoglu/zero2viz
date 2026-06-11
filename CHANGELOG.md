# Changelog

All notable changes to **02viz - Geospatial Visualization Studio** are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · versioning: [SemVer](https://semver.org/).

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
