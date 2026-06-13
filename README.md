<div align="center">

<img src="icons/icon.png" width="96" alt="02viz icon"/>

# 02viz — Geospatial Visualization Studio

**Geospatial data visualization studio: multi-engine, interactive, publication-quality charts from QGIS layers and external data.**

[![QGIS](https://img.shields.io/badge/QGIS-3.28%2B-93b023?logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/zero2viz/)
[![Version](https://img.shields.io/github/v/tag/YusufEminoglu/zero2viz?label=version&color=blue)](https://github.com/YusufEminoglu/zero2viz/releases)
[![License](https://img.shields.io/badge/license-GPL--3.0-orange)](LICENSE)
[![QGIS Plugin Hub](https://img.shields.io/badge/QGIS%20Hub-install-589632?logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/zero2viz/)

<img src="docs/hero-dashboard.png" width="860" alt="02viz Explore dashboard — KPI cards, auto charts, correlation matrix and a trend scatter"/>

</div>

---

## Why 02viz?

**Zero2Visual — from zero to elegant visuals, fast.** Charting in GIS has always meant exporting attribute tables to a spreadsheet, or wrestling with one fixed plotting library. 02viz puts a full visualization studio inside QGIS, organised as **one dock with three tabs — Charts, Map diagrams and Labels** — three ways to turn a layer's data into a publication-quality visual that stays linked to the map. It is built for planners, analysts and cartographers who want their visuals to match the quality of their maps.

## ✨ Features

- **One dock, three tabs** — **Charts** (interactive web charts), **Map diagrams** (native diagrams on every feature) and **Labels** (quick elegant labels), all sharing one layer selector.
- **One-click Explore** — pick a layer, press one button: 02viz profiles every field and builds a complete interactive dashboard — KPI cards, a chart per field, a Pearson correlation matrix, the strongest-relationship scatter with trend line, and plain-English insight chips ("Strongest link: pop ↔ income, r = -0.47"). Identifier columns (fid/id/gid/uuid) are skipped.
- **Seventeen chart types, zero setup** — bar (grouped/stacked), line, area, scatter, bubble, histogram, pie/donut, box plot, heatmap, treemap, sunburst, mean ± σ band, mean ± σ bars, density (KDE), violin, radar/spider and Pareto (80/20).
- **Four engines, engine-first** — pick the renderer, then choose from the chart types it can draw; the rest grey out. Three are vendored and fully offline (Apache ECharts, Plotly.js, Vega-Lite); the optional **matplotlib / seaborn** engine renders publication-grade *static* figures and installs on demand (auto-detected, one-click pip install — the core studio stays dependency-free).
- **Map diagrams on the canvas** — native QGIS **pie / bar / stacked-bar / text** diagrams on every feature, sized in millimetres and coloured with the studio palette. They print and export to layout like any symbology.
- **Quick, elegant labels** — turn any field into well-placed labels with a preset (clean subtle-halo / strong halo / bold / plain), geometry-aware placement, built on native QGIS labeling.
- **Publication-grade output** — one type system, soft dashed gridlines, clean card tooltips, rounded bars and minimal axes across every engine — charts read at Tableau quality.
- **Chart → map selection** — click a bar, slice or point and the matching features are selected on the canvas, on every QGIS web stack (crash-safe title transport, no QWebChannel needed).
- **Map → chart cross-filter** — select features on the canvas and the chart instantly dims everything else, no re-render; works in single charts and across every dashboard tile.
- **Live mode** — optionally re-render on every canvas selection change; "Only selected features" scopes any chart to your selection.
- **Built-in data shaping & statistics** — aggregation (count/sum/mean/median/min/max), group/color-by field, Top-N with "Other" collapse, value sorting, least-squares trend line, histogram binning, box-plot quartiles, sample standard deviation, Silverman-bandwidth Gaussian KDE and cumulative shares — all pure Python, no pandas/numpy needed.
- **Layers and beyond** — chart any vector layer or attribute table, or load external CSV/XLSX/ODS tables straight into the studio.
- **Four themes, eight palettes + an embedded swatch editor** — Studio Light, Ink Dark, Soft Pastel and Bold Print themes, a Colors selector with 8 curated palettes (Vivid, Colorblind safe, Viridis, Sunset, Ocean, Earth, Berry, Grayscale print), and **inline swatches right in the dock** — click one to recolour it, `+`/`−` to resize the palette. All override the theme palette identically in every engine.
- **One-file export** — every chart saves as a single self-contained interactive HTML; PNG export via the chart toolbox.
- **Qt5 and Qt6 ready** — runs on QGIS 3.28+ and the QGIS 4 line, with a WebEngine → WebKit → browser viewer fallback chain.

## 🖼️ Gallery

A few of the seventeen chart types, rendered offline by the vendored JS engines and styled for publication:

| Violin (KDE) | Radar / spider |
|:---:|:---:|
| <img src="docs/chart-violin.png" width="380" alt="Violin plot"/> | <img src="docs/chart-radar.png" width="380" alt="Radar chart"/> |
| **Pareto (80/20)** | **Correlation heatmap** |
| <img src="docs/chart-pareto.png" width="380" alt="Pareto chart"/> | <img src="docs/chart-heatmap.png" width="380" alt="Heatmap"/> |

The optional **matplotlib / seaborn** engine renders the same spec as a publication-grade static figure:

<img src="docs/engine-matplotlib.png" width="560" alt="Matplotlib/seaborn static bar chart"/>

## 🚀 Installation

**From the QGIS Plugin Hub (recommended):** `Plugins → Manage and Install Plugins…` → search for **"02viz"** → *Install*.

**From a release zip:** download the latest zip from [Releases](https://github.com/YusufEminoglu/zero2viz/releases) → `Plugins → Install from ZIP`.

Requires QGIS 3.28 or newer. **No external Python dependencies for the core studio** (the three JS engines are vendored). The optional matplotlib/seaborn engine installs on demand, with your consent, from inside the plugin.

## 📖 Quick start

1. Install 02viz and click the **02viz Studio** toolbar button — the studio dock opens on the right.
2. Pick a layer (or **Load external table…** for a CSV/XLSX), optionally tick *Only selected features*.
3. On the **Charts** tab pick the engine and chart type, set the X/Y fields and an aggregation if you want grouping.
4. Hit **Render chart** — the interactive chart appears right in the dock.
5. **Export HTML…** saves it as a single self-contained file; the chart toolbox saves PNG. The **Map diagrams** and **Labels** tabs draw straight onto the canvas.

## ⚙️ Reference

| Group | Component | What it does |
|-------|-----------|--------------|
| Data (shared) | Layer combo + selected-only | Binds any vector layer/table; respects canvas selection |
| Data (shared) | Live: redraw on selection | Re-renders the chart whenever the layer selection changes |
| Data (shared) | Load external table… | Opens CSV/XLSX/ODS/GPKG tables via OGR and adds them to the layer list |
| Charts | Engine / Type / Theme / Colors | 4 engines (ECharts, Plotly, Vega-Lite + optional matplotlib) × 17 types × 4 themes × 8 palettes + inline custom swatches |
| Charts | X / Y / Group / Value-Size / Title | Field bindings + a chart-title override; Group splits colored series, Value drives bubble size, heatmap cells and treemap weights |
| Charts | Aggregate / Bins / Top N / Sort | count·sum·mean·median·min·max, histogram bins, Top-N with "Other", value sorting |
| Charts | Render / ✨ Explore / Export / ↗ | Render to the embedded viewer (WebEngine → WebKit → browser), one-click Explore dashboard, one-file HTML export, open-in-browser fallback |
| Map diagrams | Type / Fields / Size | Native QGIS pie/bar/stacked/text diagrams on every feature, on the canvas |
| Labels | Field / Style / Size | Quick clean/halo/bold/plain labels via native QGIS labeling |

## 🧩 Part of the PlanX ecosystem

02viz is one of 16 open-source QGIS plugins for urban planning by the same author:

| Planning & analysis | CAD & production | 3D & visualization |
|---|---|---|
| [PlanX](https://github.com/YusufEminoglu/PlanX) — spatial-planning suite | [PlanX CAD Toolset](https://github.com/YusufEminoglu/PlanX-CAD) — drafting-grade CAD | [PlanX 3D City](https://github.com/YusufEminoglu/planx_3d_city) — Three.js city viewer |
| [GeoStats Lab](https://github.com/YusufEminoglu/planx_geostats) — spatial statistics | [EasyFillet](https://github.com/YusufEminoglu/EasyFillet) — tangent-arc fillet | [3D OSM Model](https://github.com/YusufEminoglu/osm_3d_model) — OSM → 3D city in browser |
| [Suitability Lab](https://github.com/YusufEminoglu/planx_suitability_lab) — raster MCDA | [Settlement Toolset](https://github.com/YusufEminoglu/PlanX-Settlement) — 9-stage settlement plans | [OSM Quick 3D](https://github.com/YusufEminoglu/osm_quick_3d) — OSM → native QGIS 3D |
| [DataCube Lab](https://github.com/YusufEminoglu/planx_datacube) — spatiotemporal cubes | [UIP Toolset](https://github.com/YusufEminoglu/PlanX-UIP) — Turkish master-plan automation | [Urban Procedural 3D](https://github.com/YusufEminoglu/planx_urban_procedural_3d) — parametric zoning lab |
| [Urban Resilience](https://github.com/YusufEminoglu/planx_urban_resilience) — 28 resilience tools | [ParcelFlux](https://github.com/YusufEminoglu/parcelflux) — parcel subdivision | [CartoLab](https://github.com/YusufEminoglu/planx_cartolab) — publication cartography |

## 📜 License & author

GPL-3.0 © [Yusuf Eminoğlu](https://github.com/YusufEminoglu) — bug reports and feature requests welcome in [Issues](https://github.com/YusufEminoglu/zero2viz/issues).
