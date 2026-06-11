<div align="center">

<img src="icons/icon.png" width="96" alt="02viz icon"/>

# 02viz — Geospatial Visualization Studio

**Elite geospatial data visualization studio: multi-engine, interactive, publication-quality charts from QGIS layers and external data.**

[![QGIS](https://img.shields.io/badge/QGIS-3.28%2B-93b023?logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/02viz/)
[![Version](https://img.shields.io/github/v/tag/YusufEminoglu/02viz?label=version&color=blue)](https://github.com/YusufEminoglu/02viz/releases)
[![License](https://img.shields.io/badge/license-GPL--3.0-orange)](LICENSE)
[![QGIS Plugin Hub](https://img.shields.io/badge/QGIS%20Hub-install-589632?logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/02viz/)

<!-- hero: docs/hero.png lands with the first feature release -->

</div>

---

## Why 02viz?

Charting in GIS has always meant exporting attribute tables to a spreadsheet, or wrestling with one fixed plotting library. 02viz puts a full visualization studio inside QGIS: pick a layer (or any external table), pick a chart, pick an engine — and get an interactive, publication-quality graphic that stays linked to the map canvas. It is built for planners, analysts and cartographers who want their charts to match the quality of their maps.

## ✨ Features

- **Multi-engine rendering** — one studio, many engines: Python, R and HTML/JavaScript chart libraries behind a single consistent UI. *(in development)*
- **Layers and beyond** — chart vector layers and attribute tables, but also external CSV/Excel/JSON sources that never touch the map. *(in development)*
- **Map-linked interactivity** — select on the chart, see it highlighted on the canvas; filter the canvas, watch the chart follow. *(in development)*
- **Publication-quality export** — vector and high-DPI raster export plus standalone interactive HTML. *(in development)*
- **Instant startup** — engines load lazily; the studio dock opens immediately and never slows QGIS down.
- **Qt5 and Qt6 ready** — runs on QGIS 3.28+ and the QGIS 4 line.

## 🚀 Installation

**From the QGIS Plugin Hub (recommended):** `Plugins → Manage and Install Plugins…` → search for **"02viz"** → *Install*.

**From a release zip:** download the latest zip from [Releases](https://github.com/YusufEminoglu/02viz/releases) → `Plugins → Install from ZIP`.

Requires QGIS 3.28 or newer. No external Python dependencies for the core studio.

## 📖 Quick start

1. Install 02viz and click the **02viz Studio** toolbar button.
2. The studio dock opens on the right — this is the home of every chart you build.
3. Chart building (data binding, engine and chart-type gallery) ships in the next releases; watch the [CHANGELOG](CHANGELOG.md).

## ⚙️ Reference

| Group | Component | What it does |
|-------|-----------|--------------|
| Studio | Studio dock | Hosts the chart builder: data binding, engine selection, chart gallery, live preview |
| Studio | Toolbar action | Toggles the studio dock |

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

GPL-3.0 © [Yusuf Eminoğlu](https://github.com/YusufEminoglu) — bug reports and feature requests welcome in [Issues](https://github.com/YusufEminoglu/02viz/issues).
