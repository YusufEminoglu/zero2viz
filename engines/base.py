# -*- coding: utf-8 -*-
"""Engine contract, themes and the shared HTML shell.

A chart engine turns a *spec* dict into one fully self-contained HTML
document (vendored JS inlined — charts must render offline and export
as a single file).

Spec contract (produced by the dock, consumed by every engine):

    {
        "type": "bar" | "line" | "area" | "scatter" | "bubble" |
                "histogram" | "pie" | "box" | "heatmap" |
                "treemap" | "sunburst",
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
        },
    }

Feature ids ("ids" / point fid) make charts clickable: the embedded
bridge forwards clicked ids to QGIS, which selects them on the canvas.
"""
from __future__ import annotations

import os

CHART_TYPES = ("bar", "line", "area", "scatter", "bubble", "histogram",
               "pie", "box", "heatmap", "treemap", "sunburst")

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

_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
_FILE_CACHE: dict[str, str] = {}

# Selection bridge bootstrap. Two transports:
#  - QtWebKit: QGIS injects window.o2vizBridge directly (addToJavaScriptWindowObject)
#  - QtWebEngine: qt.webChannelTransport + qwebchannel.js resolves the object
# In a plain browser neither exists and clicks are simply inert.
BRIDGE_JS = """
(function () {
  if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {
    new QWebChannel(qt.webChannelTransport, function (channel) {
      window.o2vizBridge = channel.objects.o2vizBridge;
    });
  }
  window.__o2vizSelect = function (ids) {
    try {
      if (window.o2vizBridge && window.o2vizBridge.select && ids && ids.length) {
        window.o2vizBridge.select(ids.filter(function (v) { return v !== null && v !== undefined; }).join(","));
      }
    } catch (e) { /* selection is best-effort */ }
  };
})();
"""

_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; background: {bg}; }}
  #chart {{ width: 100%; height: 100%; }}
</style>
<script>{qwebchannel}</script>
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
        qwebchannel=read_web("qwebchannel.js"),
        lib=lib_js,
        bridge=BRIDGE_JS,
        body=body_js,
    )


def theme_of(spec: dict) -> dict:
    return spec.get("theme") or THEMES[DEFAULT_THEME]


class ChartEngine:
    id = "base"
    label = "Base"

    def build_html(self, spec: dict) -> str:
        raise NotImplementedError
