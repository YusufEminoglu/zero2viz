# Changelog

## [0.2.0] - 2026-06-12

- First working chart studio: 6 ECharts chart types, aggregation, external tables, embedded viewer

All notable changes to **02viz - Geospatial Visualization Studio** are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · versioning: [SemVer](https://semver.org/).

## [0.2.0] - 2026-06-12

- First working chart studio: bar, line, scatter, histogram, pie/donut and box plot.
- Vendored Apache ECharts engine — interactive HTML charts, fully offline.
- Data binding: any vector layer or table, selected-features-only mode, external CSV/XLSX/ODS tables via OGR.
- Pure-Python aggregation (count/sum/mean/median/min/max), histogram binning and box-plot quartiles.
- Embedded viewer with WebEngine → WebKit → system-browser fallback chain.
- One-file interactive HTML export; PNG export via the chart toolbox.
- Verified headless on real QGIS Python (12 checks) + headless-Chrome render of all six chart types.

## [0.1.0] - 2026-06-12

- Initial scaffold: studio dock shell, toolbar action, Qt5/Qt6-compatible plugin infrastructure.
