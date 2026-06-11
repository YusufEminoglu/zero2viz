# -*- coding: utf-8 -*-
"""ECharts engine — Apache ECharts (Apache-2.0) vendored in ../web/echarts.min.js."""
from __future__ import annotations

import json
import os

from .base import ChartEngine

_VENDOR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "echarts.min.js")
_LIB_CACHE: str | None = None

# PlanX palette: teal / salmon / ink and friendly companions
PALETTE = ["#2a8f85", "#fa8e7a", "#16323f", "#7fd1c5", "#f4a261",
           "#8d99ae", "#e76f51", "#bdb8b0"]

_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; background: #fbfbfd; }}
  #chart {{ width: 100%; height: 100%; }}
</style>
<script>{lib}</script>
</head>
<body>
<div id="chart"></div>
<script>
  var chart = echarts.init(document.getElementById("chart"), null, {{ renderer: "canvas" }});
  chart.setOption({option});
  window.addEventListener("resize", function () {{ chart.resize(); }});
  window.__chartReady = true;
</script>
</body>
</html>
"""


def _lib() -> str:
    global _LIB_CACHE
    if _LIB_CACHE is None:
        with open(_VENDOR, encoding="utf-8") as f:
            _LIB_CACHE = f.read()
    return _LIB_CACHE


class EChartsEngine(ChartEngine):
    id = "echarts"
    label = "ECharts (interactive HTML)"

    def build_html(self, spec: dict) -> str:
        option = self._option(spec)
        return _HTML.format(
            title=spec.get("title", "02viz chart"),
            lib=_lib(),
            option=json.dumps(option, ensure_ascii=False),
        )

    # ───────────────────── option builders ─────────────────────

    def _option(self, spec: dict) -> dict:
        kind = spec["type"]
        data = spec.get("data", {})
        option = {
            "color": PALETTE,
            "title": {"text": spec.get("title", ""), "left": "center",
                      "textStyle": {"color": "#16323f", "fontSize": 16}},
            "tooltip": {"trigger": "item"},
            "toolbox": {"feature": {"saveAsImage": {"name": "02viz_chart"},
                                    "dataZoom": {}, "restore": {}}},
        }

        if kind in ("bar", "line", "histogram"):
            option["tooltip"] = {"trigger": "axis"}
            option["grid"] = {"left": 60, "right": 30, "bottom": 60, "top": 60}
            option["xAxis"] = {"type": "category", "data": data["categories"],
                               "name": spec.get("x_label", ""),
                               "nameLocation": "middle", "nameGap": 35,
                               "axisLabel": {"rotate": 30 if kind != "histogram" else 45}}
            option["yAxis"] = {"type": "value", "name": spec.get("y_label", "")}
            series = {"type": "bar" if kind != "line" else "line",
                      "data": data["values"],
                      "name": spec.get("y_label", "value")}
            if kind == "histogram":
                series["barWidth"] = "92%"
            if kind == "line":
                series["smooth"] = True
                series["symbolSize"] = 7
            option["series"] = [series]

        elif kind == "scatter":
            option["grid"] = {"left": 60, "right": 30, "bottom": 60, "top": 60}
            option["xAxis"] = {"type": "value", "name": spec.get("x_label", ""),
                               "nameLocation": "middle", "nameGap": 30,
                               "scale": True}
            option["yAxis"] = {"type": "value", "name": spec.get("y_label", ""),
                               "scale": True}
            option["series"] = [{"type": "scatter", "data": data["points"],
                                 "symbolSize": 9,
                                 "itemStyle": {"opacity": 0.75},
                                 "name": spec.get("y_label", "value")}]

        elif kind == "pie":
            option["series"] = [{
                "type": "pie", "radius": ["35%", "68%"],
                "itemStyle": {"borderRadius": 6, "borderColor": "#fbfbfd", "borderWidth": 2},
                "label": {"formatter": "{b}: {c}"},
                "data": [{"name": c, "value": v}
                         for c, v in zip(data["categories"], data["values"])],
            }]

        elif kind == "box":
            option["tooltip"] = {"trigger": "item"}
            option["grid"] = {"left": 60, "right": 30, "bottom": 60, "top": 60}
            option["xAxis"] = {"type": "category", "data": data["groups"],
                               "name": spec.get("x_label", ""),
                               "nameLocation": "middle", "nameGap": 35}
            option["yAxis"] = {"type": "value", "name": spec.get("y_label", ""),
                               "scale": True}
            option["series"] = [{"type": "boxplot", "data": data["stats"],
                                 "name": spec.get("y_label", "value")}]

        else:
            raise ValueError(f"Unsupported chart type: {kind}")

        return option
