# -*- coding: utf-8 -*-
"""ECharts engine — Apache ECharts (Apache-2.0) vendored in ../web/echarts.min.js."""
from __future__ import annotations

import json
import math

from .base import ChartEngine, read_web, theme_of, wrap_html

_BODY = """
var chart = echarts.init(document.getElementById("chart"), null, { renderer: "canvas" });
var OPT = %(option)s;
// JSON cannot carry functions: custom-series renderers and numeric-axis
// category labels are attached here, after parse.
function __o2vizViolinRender(params, api) {
  var item = OPT.series[params.seriesIndex].data[params.dataIndex];
  var poly = item.__poly || [];
  var col = (item.itemStyle && item.itemStyle.color) || api.visual("color");
  var pts = [];
  for (var i = 0; i < poly.length; i++) pts.push(api.coord(poly[i]));
  return { type: "polygon", shape: { points: pts },
           style: { fill: col, stroke: col, lineWidth: 1.2, opacity: 0.6 } };
}
function __o2vizWhiskerRender(params, api) {
  var s = OPT.series[params.seriesIndex];
  var n = s.__sn || 1, j = s.__si || 0;
  var band = api.size([1, 0])[0];
  // replicate the bar layout (barCategoryGap 0.2, barGap 0.3 — keep in sync
  // with the python errorbar branch) so whiskers sit exactly on their bars
  var w = band * 0.8 / (n + 0.3 * (n - 1));
  var cx = api.coord([api.value(0), 0])[0] - 0.4 * band + w * (j + 0.5 + 0.3 * j);
  var lo = api.coord([api.value(0), api.value(1)])[1];
  var hi = api.coord([api.value(0), api.value(2)])[1];
  var half = Math.min(9, w * 0.3);
  var ls = { stroke: s.__color || api.visual("color"), lineWidth: 1.6 };
  return { type: "group", children: [
    { type: "line", shape: { x1: cx, y1: lo, x2: cx, y2: hi }, style: ls },
    { type: "line", shape: { x1: cx - half, y1: lo, x2: cx + half, y2: lo }, style: ls },
    { type: "line", shape: { x1: cx - half, y1: hi, x2: cx + half, y2: hi }, style: ls }
  ] };
}
(OPT.series || []).forEach(function (s) {
  if (s.__render === "violin") s.renderItem = __o2vizViolinRender;
  if (s.__render === "whisker") s.renderItem = __o2vizWhiskerRender;
});
if (OPT.__xnames && OPT.xAxis && OPT.xAxis.type === "value") {
  OPT.xAxis.axisLabel = OPT.xAxis.axisLabel || {};
  OPT.xAxis.axisLabel.formatter = function (v) {
    return (Math.abs(v - Math.round(v)) < 1e-6 && OPT.__xnames[Math.round(v)]) || "";
  };
}
chart.setOption(OPT);
window.addEventListener("resize", function () { chart.resize(); });
chart.on("click", function (p) {
  var ids = p.data && p.data.__ids;
  if (ids && ids.length) __o2vizSelect(ids);
});
// map → chart cross-filter: QGIS injects __o2vizHighlight(ids) on selection
// change; items carrying __ids dim unless one of their features is selected.
window.__o2vizHighlight = function (ids) {
  try {
    var want = null, i;
    if (ids && ids.length) {
      want = {};
      for (i = 0; i < ids.length; i++) want[ids[i]] = true;
    }
    var series = OPT.series || [], touched = false;
    for (var si = 0; si < series.length; si++) {
      var d = series[si].data || [];
      for (var di = 0; di < d.length; di++) {
        var it = d[di];
        if (!it || it.constructor !== Object || !it.__ids || !it.__ids.length) continue;
        it.itemStyle = it.itemStyle || {};
        if (want === null) {
          delete it.itemStyle.opacity;  // notMerge redraw restores series defaults
        } else {
          var hit = false;
          for (i = 0; i < it.__ids.length; i++) if (want[it.__ids[i]]) { hit = true; break; }
          it.itemStyle.opacity = hit ? 1 : 0.16;
        }
        touched = true;
      }
    }
    if (touched) chart.setOption(OPT, true);
    window.__o2vizHighlighted = (want === null) ? -1 : ids.length;
  } catch (e) { /* highlight is best-effort */ }
};
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


def _padded_range(lo: float, hi: float) -> tuple[float, float]:
    """Pad a value range by 5 percent, round to friendly axis bounds."""
    span = (hi - lo) or abs(hi) or 1.0
    lo, hi = lo - span * 0.05, hi + span * 0.05
    if span > 5:
        return math.floor(lo), math.ceil(hi)
    return round(lo, 3), round(hi, 3)


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
            # per-cell labels: white only where the ramp is dark — both extremes
            # on a diverging ramp, only the upper end on a sequential one
            # (low sequential cells are near the background colour)
            mid = (vmin + vmax) / 2.0
            span = (vmax - vmin) or 1.0
            items = []
            for cell in data.get("cells", []):
                v = cell[2]
                if data.get("diverging"):
                    intense = abs(v - mid) > span * 0.28
                else:
                    intense = (v - vmin) > span * 0.72
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

        elif kind in ("errorband", "errorbar"):
            option["grid"] = grid
            option["xAxis"] = _axis(theme, spec.get("x_label", ""), "category",
                                    data.get("categories", []), rotate=30)
            option["yAxis"] = _axis(theme, spec.get("y_label", ""),
                                    zero=kind == "errorbar")
            series_in = data.get("series", [])
            if len(series_in) > 1:
                option["legend"] = {"top": 28, "textStyle": {"color": theme["text"]},
                                    "data": [s.get("name", "") for s in series_in]}
            out = []
            for si, s in enumerate(series_in):
                color = theme["palette"][si % len(theme["palette"])]
                mean, lo, hi = s.get("mean", []), s.get("lo", []), s.get("hi", [])
                if kind == "errorband":
                    band = [None if (h is None or lo[i] is None) else h - lo[i]
                            for i, h in enumerate(hi)]
                    helper = {"lineStyle": {"opacity": 0}, "symbol": "none",
                              "stack": f"band{si}", "silent": True,
                              "tooltip": {"show": False}}
                    out.append(dict(helper, name=f"{s.get('name', '')}·lo",
                                    type="line", data=lo))
                    out.append(dict(helper, name=f"{s.get('name', '')}·hi",
                                    type="line", data=band,
                                    areaStyle={"color": color, "opacity": 0.18}))
                    out.append({"name": s.get("name", ""), "type": "line",
                                "data": _with_ids(mean, s.get("ids")),
                                "itemStyle": {"color": color},
                                "lineStyle": {"color": color},
                                "symbolSize": 7, "z": 3})
                else:
                    out.append({"name": s.get("name", ""), "type": "bar",
                                "data": _with_ids(mean, s.get("ids")),
                                "itemStyle": {"color": color},
                                "barCategoryGap": "20%", "barGap": "30%"})
                    out.append({"name": f"{s.get('name', '')}·σ", "type": "custom",
                                "__render": "whisker", "__si": si,
                                "__sn": len(series_in),
                                "__color": theme["text"],
                                "data": [[i, lo[i], hi[i]] for i in range(len(mean))
                                         if lo[i] is not None],
                                "silent": True, "z": 3, "tooltip": {"show": False}})
            if kind == "errorbar":
                # custom-series whiskers don't drive the axis extent — without
                # an explicit max the +σ caps get clipped at the chart top
                all_lo = [v for s in series_in for v in s.get("lo", []) if v is not None]
                all_hi = [v for s in series_in for v in s.get("hi", []) if v is not None]
                if all_hi:
                    lo_b, hi_b = _padded_range(min(all_lo + [0.0]), max(all_hi))
                    option["yAxis"]["max"] = hi_b
                    if min(all_lo) < 0:
                        option["yAxis"]["min"] = lo_b
            option["series"] = out

        elif kind == "density":
            option["grid"] = grid
            option["xAxis"] = _axis(theme, spec.get("x_label", ""))
            option["yAxis"] = _axis(theme, spec.get("y_label", "density"), zero=True)
            series_in = data.get("series", [])
            if len(series_in) > 1:
                option["legend"] = {"top": 28, "textStyle": {"color": theme["text"]}}
            option["series"] = [{"name": s.get("name", ""), "type": "line",
                                 "data": s.get("points", []), "smooth": True,
                                 "symbol": "none", "areaStyle": {"opacity": 0.3}}
                                for s in series_in]

        elif kind == "violin":
            groups = data.get("groups", [])
            option["grid"] = grid
            option["xAxis"] = dict(_axis(theme, spec.get("x_label", "")),
                                   min=-1, max=len(groups), interval=1)
            option["yAxis"] = _axis(theme, spec.get("y_label", ""))
            # custom-series polygons don't drive the axis extent either
            all_y = [p[1] for poly in data.get("polygons", []) for p in poly]
            if all_y:
                y_lo, y_hi = _padded_range(min(all_y), max(all_y))
                option["yAxis"]["min"] = y_lo
                option["yAxis"]["max"] = y_hi
            option["__xnames"] = groups
            option["series"] = [
                {"type": "custom", "__render": "violin",
                 "data": [{"value": [i, data.get("medians", [None] * len(groups))[i]],
                           "name": g, "__poly": data.get("polygons", [])[i],
                           "itemStyle": {
                               "color": theme["palette"][i % len(theme["palette"])],
                               "opacity": 0.55}}
                          for i, g in enumerate(groups)]},
                {"type": "scatter", "silent": True, "symbolSize": 7,
                 "itemStyle": {"color": theme["text"]}, "z": 3,
                 "data": [[i, m] for i, m in enumerate(data.get("medians", []))]},
            ]

        elif kind == "radar":
            axes = data.get("axes", [])
            maxes = data.get("maxes", [])
            option["radar"] = {
                "center": ["50%", "56%"], "radius": "62%",
                "indicator": [{"name": a, "max": maxes[i] if i < len(maxes) else None}
                              for i, a in enumerate(axes)],
                "axisName": {"color": theme["text"]},
                "axisLine": {"lineStyle": {"color": theme["grid"]}},
                "splitLine": {"lineStyle": {"color": theme["grid"]}},
                "splitArea": {"show": False},
            }
            series_in = data.get("series", [])
            if len(series_in) > 1:
                option["legend"] = {"top": 28, "textStyle": {"color": theme["text"]}}
            option["series"] = [{"type": "radar", "symbolSize": 5,
                                 "data": [{"name": s.get("name", ""),
                                           "value": s.get("values", []),
                                           "areaStyle": {"opacity": 0.22}}
                                          for s in series_in]}]

        elif kind == "pareto":
            option["tooltip"] = {"trigger": "axis"}
            option["grid"] = dict(grid, right=64)
            option["xAxis"] = _axis(theme, spec.get("x_label", ""), "category",
                                    data.get("categories", []), rotate=30)
            pct_axis = _axis(theme, "cumulative %")
            pct_axis.update(min=0, max=100, splitLine={"show": False})
            pct_axis["axisLabel"]["formatter"] = "{value} %"
            option["yAxis"] = [_axis(theme, spec.get("y_label", ""), zero=True),
                               pct_axis]
            option["series"] = [
                {"name": spec.get("y_label", "value"), "type": "bar",
                 "data": _with_ids(data.get("values", []), data.get("ids"))},
                {"name": "cumulative %", "type": "line", "yAxisIndex": 1,
                 "data": data.get("cum", []), "symbolSize": 6,
                 "itemStyle": {"color": theme["palette"][2 % len(theme["palette"])]},
                 "lineStyle": {"color": theme["palette"][2 % len(theme["palette"])]}},
            ]

        else:
            raise ValueError(f"Unsupported chart type: {kind}")

        return option
