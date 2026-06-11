# -*- coding: utf-8 -*-
"""ECharts engine — Apache ECharts (Apache-2.0) vendored in ../web/echarts.min.js."""
from __future__ import annotations

import json

from .base import ChartEngine, read_web, theme_of, wrap_html

_BODY = """
var chart = echarts.init(document.getElementById("chart"), null, { renderer: "canvas" });
chart.setOption(%(option)s);
window.addEventListener("resize", function () { chart.resize(); });
chart.on("click", function (p) {
  var ids = p.data && p.data.__ids;
  if (ids && ids.length) __o2vizSelect(ids);
});
window.__chartReady = true;
"""


def _axis(theme: dict, name: str, kind: str = "value", data=None, rotate: int = 0,
          zero: bool = False) -> dict:
    ax = {"type": kind, "name": name, "nameLocation": "middle",
          "nameGap": 38 if kind == "category" else 42,
          "nameTextStyle": {"color": theme["text"]},
          "axisLabel": {"color": theme["text"]},
          "axisLine": {"lineStyle": {"color": theme["grid"]}},
          "splitLine": {"lineStyle": {"color": theme["grid"]}}}
    if kind == "category":
        ax["data"] = data or []
        if rotate:
            ax["axisLabel"]["rotate"] = rotate
    else:
        # bars/areas must start at zero or relative sizes lie to the reader
        ax["scale"] = not zero
    return ax


def _with_ids(values: list, ids: list | None) -> list:
    if not ids:
        return values
    return [{"value": v, "__ids": ids[i] if i < len(ids) else []}
            for i, v in enumerate(values)]


class EChartsEngine(ChartEngine):
    id = "echarts"
    label = "ECharts"

    def build_html(self, spec: dict) -> str:
        option = self.option(spec)
        return wrap_html(spec.get("title", ""), read_web("echarts.min.js"),
                         _BODY % {"option": json.dumps(option, ensure_ascii=False)},
                         theme_of(spec))

    def option(self, spec: dict) -> dict:
        """Public: the ECharts option for a spec (reused by the dashboard)."""
        return self._option(spec)

    # ───────────────────── option builder ─────────────────────

    def _option(self, spec: dict) -> dict:
        kind = spec["type"]
        data = spec.get("data", {})
        theme = theme_of(spec)
        option: dict = {
            "color": theme["palette"],
            "backgroundColor": theme["bg"],
            "textStyle": {"color": theme["text"]},
            "title": {"text": spec.get("title", ""), "left": "center",
                      "textStyle": {"color": theme["text"], "fontSize": 16}},
            "tooltip": {"trigger": "item"},
            "toolbox": {"feature": {"saveAsImage": {"name": "02viz_chart"},
                                    "dataZoom": {}, "restore": {}}},
        }
        grid = {"left": 64, "right": 30, "bottom": 64, "top": 70, "containLabel": False}

        if kind in ("bar", "line", "area", "histogram"):
            series_in = data.get("series") or [{"name": spec.get("y_label", "value"),
                                                "values": data.get("values", []),
                                                "ids": data.get("ids")}]
            option["tooltip"] = {"trigger": "axis"}
            option["grid"] = grid
            option["xAxis"] = _axis(theme, spec.get("x_label", ""), "category",
                                    data.get("categories", []),
                                    rotate=45 if kind == "histogram" else 30)
            option["yAxis"] = _axis(theme, spec.get("y_label", ""),
                                    zero=kind in ("bar", "area", "histogram"))
            if len(series_in) > 1:
                option["legend"] = {"top": 28, "textStyle": {"color": theme["text"]}}
            out = []
            for s in series_in:
                item = {"name": s.get("name", ""), "type": "line" if kind in ("line", "area") else "bar",
                        "data": _with_ids(s.get("values", []), s.get("ids"))}
                if kind == "histogram":
                    item["barWidth"] = "92%"
                if kind in ("line", "area"):
                    item["smooth"] = True
                    item["symbolSize"] = 7
                if kind == "area":
                    item["areaStyle"] = {"opacity": 0.35}
                if spec.get("stacked") and kind in ("bar", "area"):
                    item["stack"] = "total"
                out.append(item)
            option["series"] = out

        elif kind in ("scatter", "bubble"):
            option["grid"] = grid
            option["xAxis"] = _axis(theme, spec.get("x_label", ""))
            option["yAxis"] = _axis(theme, spec.get("y_label", ""))
            series_in = data.get("series", [])
            if len(series_in) > 1:
                option["legend"] = {"top": 28, "textStyle": {"color": theme["text"]}}
            out = []
            for s in series_in:
                pts = []
                for p in s.get("points", []):
                    item = {"value": [p[0], p[1]],
                            "__ids": [p[3]] if len(p) > 3 and p[3] is not None else []}
                    if len(p) > 2 and p[2] is not None:
                        item["symbolSize"] = p[2]
                    pts.append(item)
                out.append({"name": s.get("name", ""), "type": "scatter", "data": pts,
                            "symbolSize": 9 if kind == "scatter" else None,
                            "itemStyle": {"opacity": 0.78}})
            trend = data.get("trend")
            if trend:
                out.append({"name": "trend", "type": "line", "data": trend,
                            "showSymbol": False, "smooth": False,
                            "lineStyle": {"type": "dashed", "width": 2},
                            "tooltip": {"show": False}, "silent": True})
            option["series"] = out

        elif kind == "pie":
            option["series"] = [{
                "type": "pie", "radius": ["35%", "68%"],
                "itemStyle": {"borderRadius": 6, "borderColor": theme["bg"], "borderWidth": 2},
                "label": {"formatter": "{b}: {c}", "color": theme["text"]},
                "data": [{"name": c, "value": v,
                          "__ids": (data.get("ids") or [[]] * len(data["categories"]))[i]}
                         for i, (c, v) in enumerate(zip(data["categories"], data["values"]))],
            }]

        elif kind == "box":
            option["grid"] = grid
            option["xAxis"] = _axis(theme, spec.get("x_label", ""), "category",
                                    data.get("groups", []))
            option["yAxis"] = _axis(theme, spec.get("y_label", ""))
            option["series"] = [{"type": "boxplot", "data": data.get("stats", []),
                                 "name": spec.get("y_label", "value")}]

        elif kind == "heatmap":
            option["grid"] = dict(grid, bottom=110)
            option["xAxis"] = _axis(theme, spec.get("x_label", ""), "category",
                                    data.get("x_cats", []), rotate=30)
            option["yAxis"] = _axis(theme, spec.get("y_label", ""), "category",
                                    data.get("y_cats", []))
            option["yAxis"]["nameGap"] = 70
            vmin, vmax = data.get("vmin", 0), data.get("vmax", 1)
            if data.get("diverging"):
                ramp = [theme["palette"][1], theme["bg"], theme["palette"][0]]
            else:
                ramp = [theme["bg"], theme["palette"][0], theme["palette"][2]]
            option["visualMap"] = {
                "min": vmin, "max": vmax,
                "calculable": True, "orient": "horizontal", "left": "center", "bottom": 6,
                "textStyle": {"color": theme["text"]},
                "inRange": {"color": ramp},
            }
            # per-cell labels: white on intense cells, theme text near the middle
            mid = (vmin + vmax) / 2.0
            span = (vmax - vmin) or 1.0
            items = []
            for cell in data.get("cells", []):
                v = cell[2]
                intense = abs(v - mid) > span * 0.28
                txt = f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.3g}"
                items.append({"value": cell,
                              "label": {"color": "#ffffff" if intense else theme["text"],
                                        "formatter": txt}})
            option["series"] = [{"type": "heatmap", "data": items,
                                 "label": {"show": True}}]

        elif kind in ("treemap", "sunburst"):
            nodes = data.get("nodes", [])
            if kind == "treemap":
                option["series"] = [{"type": "treemap", "data": nodes,
                                     "roam": False, "breadcrumb": {"show": False},
                                     "label": {"show": True},
                                     "upperLabel": {"show": True, "height": 22}}]
            else:
                option["series"] = [{"type": "sunburst", "data": nodes,
                                     "radius": [0, "90%"],
                                     "label": {"rotate": "radial"}}]

        else:
            raise ValueError(f"Unsupported chart type: {kind}")

        return option
