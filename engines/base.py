# -*- coding: utf-8 -*-
"""Engine contract, themes and the shared HTML shell.

A chart engine turns a *spec* dict into one fully self-contained HTML
document (vendored JS inlined — charts must render offline and export
as a single file).

Spec contract (produced by the dock, consumed by every engine):

    {
        "type": "bar" | "line" | "area" | "scatter" | "bubble" |
                "histogram" | "pie" | "box" | "heatmap" |
                "treemap" | "sunburst" | "errorband" | "errorbar" |
                "density" | "violin" | "radar" | "pareto",
        "title": str, "x_label": str, "y_label": str,
        "stacked": bool,                  # bar / area
        "theme": {"palette": [...], "bg": str, "text": str, "grid": str},
        "data": {
            # bar / line / area:
            "categories": [...], "series": [{"name", "values", "ids"}],
            # scatter / bubble:
            "series": [{"name", "points": [[x, y, size|None, fid|None]]}],
            "trend": [[x0, y0], [x1, y1]] | None,
            # histogram:  "categories", "values"
            # pie:        "categories", "values", "ids"
            # box:        "groups", "stats" ([min, q1, med, q3, max])
            # heatmap:    "x_cats", "y_cats", "cells" [[xi, yi, v]], "vmin", "vmax"
            # treemap / sunburst: "nodes" [{name, value, children?}]
            # errorband / errorbar:
            #   "categories", "series" [{"name", "mean", "lo", "hi", "ids"}]
            # density:    "series" [{"name", "points": [[x, density]]}]
            # violin:     "groups", "polygons" [[[x, y]...]], "medians"
            # radar:      "axes", "maxes", "series" [{"name", "values"}]
            # pareto:     "categories", "values", "cum" (0–100 %), "ids"
        },
    }

Feature ids ("ids" / point fid) make charts clickable: the embedded
bridge forwards clicked ids to QGIS, which selects them on the canvas.
"""
from __future__ import annotations

import os

CHART_TYPES = ("bar", "line", "area", "scatter", "bubble", "histogram",
               "pie", "box", "heatmap", "treemap", "sunburst",
               "errorband", "errorbar", "density", "violin", "radar", "pareto")

THEMES: dict[str, dict] = {
    "Studio Light": {"palette": ["#2a8f85", "#fa8e7a", "#16323f", "#7fd1c5",
                                 "#f4a261", "#8d99ae", "#e76f51", "#bdb8b0"],
                     "bg": "#fbfbfd", "text": "#16323f", "grid": "#e3e7ec"},
    "Ink Dark": {"palette": ["#4fd1c5", "#ff9e8a", "#9bb3c0", "#ffd166",
                             "#8ecae6", "#c891d9", "#a3e36b", "#f28482"],
                 "bg": "#131c21", "text": "#dfe7ea", "grid": "#2b3a42"},
    "Soft Pastel": {"palette": ["#a8dadc", "#ffb4a2", "#cdb4db", "#b5e48c",
                                "#ffd6a5", "#90caf9", "#f1c0e8", "#d3d3d3"],
                    "bg": "#ffffff", "text": "#4a4e69", "grid": "#ececec"},
    "Bold Print": {"palette": ["#0a9396", "#bb3e03", "#001219", "#ee9b00",
                               "#005f73", "#9b2226", "#94d2bd", "#6c757d"],
                   "bg": "#ffffff", "text": "#001219", "grid": "#dddddd"},
}
DEFAULT_THEME = "Studio Light"

# Colour palettes the user can swap in over any theme. ``None`` keeps the
# theme's own palette. Every engine reads spec["theme"]["palette"], so one
# override in the dock recolours ECharts, Plotly and Vega-Lite alike.
PALETTES: dict[str, list[str] | None] = {
    "Theme default": None,
    "Vivid": ["#3a86ff", "#fb5607", "#06a77d", "#d62246", "#8338ec",
              "#ffbe0b", "#118ab2", "#6c757d"],
    "Colorblind safe": ["#0072b2", "#e69f00", "#009e73", "#cc79a7",
                        "#56b4e9", "#d55e00", "#f0e442", "#999999"],
    "Viridis": ["#440154", "#46327e", "#365c8d", "#277f8e", "#1fa187",
                "#4ac16d", "#a0da39", "#fde725"],
    "Sunset": ["#5c53a5", "#a059a0", "#ce6693", "#eb7f86", "#f8a07e",
               "#fac484", "#f3e79b", "#8d99ae"],
    "Ocean": ["#03045e", "#0077b6", "#00b4d8", "#90e0ef", "#2a9d8f",
              "#197278", "#52b69a", "#8d99ae"],
    "Earth": ["#606c38", "#bc6c25", "#283618", "#dda15e", "#7f5539",
              "#a98467", "#936639", "#b6ad90"],
    "Berry": ["#590d22", "#a4133c", "#ff4d6d", "#c9184a", "#ff8fa3",
              "#7b2cbf", "#9d4edd", "#c77dff"],
    "Grayscale print": ["#1a1a1a", "#4d4d4d", "#7a7a7a", "#a6a6a6",
                        "#c9c9c9", "#333333", "#5f5f5f", "#8c8c8c"],
}

_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
_FILE_CACHE: dict[str, str] = {}

# Selection bridge bootstrap — title transport.
#
# QGIS ships a fragile QtWebKit fork: addToJavaScriptWindowObject crashes
# with an access violation inside WebCore during page commit (observed on
# QGIS 3.44 / Qt 5.15). QWebChannel only exists on WebEngine. The one
# mechanism that is safe and identical on BOTH web stacks is the page
# title: the chart encodes clicked feature ids into document.title and
# the dock listens to the view's titleChanged signal. In a plain browser
# the title blips and nothing else happens.
BRIDGE_JS = """
(function () {
  var seq = 0;
  window.__o2vizSelect = function (ids) {
    try {
      if (!ids || !ids.length) return;
      var clean = ids.filter(function (v) { return v !== null && v !== undefined; });
      if (!clean.length) return;
      seq += 1;
      document.title = "o2viz-select:" + clean.join(",") + ":" + seq;
    } catch (e) { /* selection is best-effort */ }
  };
})();
"""
TITLE_PREFIX = "o2viz-select:"

_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; background: {bg}; }}
  #chart {{ width: 100%; height: 100%; }}
</style>
<script>{lib}</script>
</head>
<body>
<div id="chart"></div>
<script>
{bridge}
{body}
</script>
</body>
</html>
"""


def read_web(filename: str) -> str:
    if filename not in _FILE_CACHE:
        with open(os.path.join(_WEB_DIR, filename), encoding="utf-8") as f:
            _FILE_CACHE[filename] = f.read()
    return _FILE_CACHE[filename]


def wrap_html(title: str, lib_js: str, body_js: str, theme: dict) -> str:
    return _HTML.format(
        title=title or "02viz chart",
        bg=theme.get("bg", "#ffffff"),
        lib=lib_js,
        bridge=BRIDGE_JS,
        body=body_js,
    )


def theme_of(spec: dict) -> dict:
    return spec.get("theme") or THEMES[DEFAULT_THEME]


class ChartEngine:
    id = "base"
    label = "Base"
    supports = frozenset(CHART_TYPES)  # engines may declare a reduced set

    def build_html(self, spec: dict) -> str:
        raise NotImplementedError
