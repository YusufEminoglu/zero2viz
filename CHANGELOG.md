# Changelog

All notable changes to **02viz - Geospatial Visualization Studio** are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · versioning: [SemVer](https://semver.org/).

## [0.1.0] - 2026-06-12

- Chart studio MVP: bar, line, scatter, histogram, pie/donut and box plot rendered by a vendored Apache ECharts engine (interactive HTML, fully offline).
- Data binding: any vector layer or table, selected-features-only mode, external CSV/XLSX/ODS tables via OGR.
- Pure-Python aggregation (count/sum/mean/median/min/max), histogram binning, box-plot quartiles.
- Embedded viewer with WebEngine → WebKit → system-browser fallback chain; one-file interactive HTML export.
