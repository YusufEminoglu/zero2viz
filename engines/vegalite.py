# -*- coding: utf-8 -*-
"""Vega-Lite engine — vega (BSD-3) + vega-lite (BSD-3) vendored in ../web/.

The declarative grammar engine: every chart is one Vega-Lite spec compiled
in the page (``vegaLite.compile`` → ``vega.View``), no vega-embed needed.
Treemap and sunburst are not part of the Vega-Lite grammar, so this engine
declares a reduced ``supports`` set and the dock greys those types out.
"""
from __future__ import annotations

import json

from .base import CHART_TYPES, ChartEngine, read_web, theme_of, wrap_html

_BODY = """
var SPEC = %(spec)s;
var VALUES = (SPEC.data && SPEC.data.values) || [];
VALUES.forEach(function (d) { if (d.__op === undefined) d.__op = 1; d.__op0 = d.__op; });
var view = null;
function render() {
  if (view) view.finalize();
  view = new vega.View(vega.parse(vegaLite.compile(SPEC).spec),
                       { renderer: "canvas", container: "#chart", hover: true });
  view.addEventListener("click", function (event, item) {
    var ids = item && item.datum && item.datum.__ids;
    if (ids && ids.length) __o2vizSelect(ids);
  });
  view.runAsync().then(function () { window.__chartReady = true; });
}
render();
window.addEventListener("resize", function () { if (view) { view.resize(); view.runAsync(); } });
// map → chart cross-filter: rows carrying __ids dim unless selected.
window.__o2vizHighlight = function (ids) {
  try {
    var want = null, i, dim = 0;
    if (ids && ids.length) {
      want = {};
      for (i = 0; i < ids.length; i++) want[ids[i]] = true;
    }
    VALUES.forEach(function (d) {
      if (!d.__ids || !d.__ids.length || want === null) { d.__op = d.__op0; return; }
      var hit = false;
      for (var k = 0; k < d.__ids.length; k++) if (want[d.__ids[k]]) { hit = true; break; }
      d.__op = hit ? d.__op0 : 0.16;
      if (!hit) dim++;
    });
    render();
    window.__o2vizDimCount = dim;
    window.__o2vizHighlighted = (want === null) ? -1 : ids.length;
  } catch (e) { /* highlight is best-effort */ }
};
"""

# per-datum opacity channel; raw values via scale:null (1 = normal, 0.16 = dimmed)
_OPACITY = {"field": "__op", "type": "quantitative", "scale": None, "legend": None}


def _axis_x(label: str, angle: int = -30) -> dict:
    return {"field": "c", "type": "nominal", "sort": None,
            "title": label or None, "axis": {"labelAngle": angle}}


class VegaLiteEngine(ChartEngine):
    id = "vegalite"
    label = "Vega-Lite"
    # no treemap/sunburst (not in the grammar) and no radar (no polar coords)
    supports = frozenset(set(CHART_TYPES) - {"treemap", "sunburst", "radar"})

    def build_html(self, spec: dict) -> str:
        vl = self.vl_spec(spec)
        lib = read_web("vega.min.js") + "\n" + read_web("vega-lite.min.js")
        return wrap_html(spec.get("title", ""), lib,
                         _BODY % {"spec": json.dumps(vl, ensure_ascii=False)},
                         theme_of(spec))

    # ───────────────────── spec builder ─────────────────────

    def vl_spec(self, spec: dict) -> dict:
        """Public: the Vega-Lite spec for a chart spec (also the future
        starting point of the custom spec editor)."""
        kind = spec["type"]
        if kind not in self.supports:
            raise ValueError(f"Vega-Lite engine does not support: {kind}")
        data = spec.get("data", {})
        theme = theme_of(spec)
        out: dict = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": spec.get("title", "") or None,
            "width": "container", "height": "container",
            "autosize": {"type": "fit", "contains": "padding"},
            "config": self._config(theme),
        }
        builder = getattr(self, f"_vl_{kind}")
        out.update(builder(spec, data, theme))
        return out

    def _config(self, theme: dict) -> dict:
        t, g = theme["text"], theme["grid"]
        return {
            "background": theme["bg"],
            "font": "Segoe UI, system-ui, sans-serif",
            "range": {"category": theme["palette"]},
            "axis": {"labelColor": t, "titleColor": t, "gridColor": g,
                     "domainColor": g, "tickColor": g},
            "legend": {"labelColor": t, "titleColor": t},
            "title": {"color": t, "fontSize": 16},
            "view": {"stroke": None},
        }

    # — categorical family —

    def _cat_rows(self, spec: dict, data: dict) -> tuple[list, list]:
        series_in = data.get("series") or [{"name": spec.get("y_label", "value"),
                                            "values": data.get("values", []),
                                            "ids": data.get("ids")}]
        cats = data.get("categories", [])
        rows = []
        for s in series_in:
            vals = s.get("values", [])
            ids = s.get("ids") or []
            for i, cat in enumerate(cats):
                if i >= len(vals):
                    break
                rows.append({"c": cat, "s": s.get("name", ""), "v": vals[i],
                             "__ids": ids[i] if i < len(ids) else []})
        return rows, series_in

    def _vl_bar(self, spec, data, theme, *, mark=None):
        rows, series_in = self._cat_rows(spec, data)
        enc = {
            "x": _axis_x(spec.get("x_label", "")),
            "y": {"field": "v", "type": "quantitative",
                  "title": spec.get("y_label", "") or None},
            "opacity": _OPACITY,
            "tooltip": [{"field": "c", "title": spec.get("x_label") or "category"},
                        {"field": "s", "title": "series"},
                        {"field": "v", "title": spec.get("y_label") or "value"}],
        }
        if len(series_in) > 1:
            enc["color"] = {"field": "s", "type": "nominal", "sort": None,
                            "title": None}
            if not spec.get("stacked"):
                enc["xOffset"] = {"field": "s", "sort": None}
        return {"data": {"values": rows},
                "mark": mark or {"type": "bar"}, "encoding": enc}

    def _vl_histogram(self, spec, data, theme):
        rows = [{"c": c, "v": v, "__ids": []}
                for c, v in zip(data.get("categories", []), data.get("values", []))]
        return {"data": {"values": rows},
                "mark": {"type": "bar", "binSpacing": 1},
                "encoding": {
                    "x": _axis_x(spec.get("x_label", ""), angle=-45),
                    "y": {"field": "v", "type": "quantitative", "title": "count"},
                    "tooltip": [{"field": "c", "title": "bin"},
                                {"field": "v", "title": "count"}],
                }}

    def _vl_lineish(self, spec, data, theme, *, mark):
        rows, series_in = self._cat_rows(spec, data)
        enc = {
            "x": _axis_x(spec.get("x_label", "")),
            "y": {"field": "v", "type": "quantitative",
                  "title": spec.get("y_label", "") or None},
            "tooltip": [{"field": "c", "title": spec.get("x_label") or "category"},
                        {"field": "s", "title": "series"},
                        {"field": "v", "title": spec.get("y_label") or "value"}],
        }
        if len(series_in) > 1:
            enc["color"] = {"field": "s", "type": "nominal", "sort": None, "title": None}
        if mark["type"] == "area" and not spec.get("stacked"):
            enc["y"]["stack"] = None
        return {"data": {"values": rows}, "mark": mark, "encoding": enc}

    def _vl_line(self, spec, data, theme):
        return self._vl_lineish(spec, data, theme,
                                mark={"type": "line", "point": True,
                                      "interpolate": "monotone", "strokeWidth": 2.5})

    def _vl_area(self, spec, data, theme):
        return self._vl_lineish(spec, data, theme,
                                mark={"type": "area", "line": True, "point": True,
                                      "interpolate": "monotone", "opacity": 0.45})

    def _vl_pie(self, spec, data, theme):
        ids = data.get("ids") or [[]] * len(data.get("categories", []))
        rows = [{"c": c, "v": v, "__ids": ids[i]}
                for i, (c, v) in enumerate(zip(data.get("categories", []),
                                               data.get("values", [])))]
        return {"data": {"values": rows},
                "mark": {"type": "arc", "innerRadius": 55,
                         "stroke": theme["bg"], "strokeWidth": 2},
                "encoding": {
                    "theta": {"field": "v", "type": "quantitative"},
                    "color": {"field": "c", "type": "nominal", "sort": None,
                              "title": None},
                    "opacity": _OPACITY,
                    "tooltip": [{"field": "c", "title": "category"},
                                {"field": "v", "title": "value"}],
                }}

    # — point family —

    def _vl_points(self, spec, data, theme, *, sized: bool):
        rows, trend = [], data.get("trend")
        for s in data.get("series", []):
            for p in s.get("points", []):
                row = {"x": p[0], "y": p[1], "s": s.get("name", ""),
                       "__ids": [p[3]] if len(p) > 3 and p[3] is not None else [],
                       "__op": 0.78}
                if sized and len(p) > 2 and p[2] is not None:
                    # vega-lite size = mark area (px²); p[2] is a symbol diameter
                    row["sz"] = round(p[2] * p[2] * 0.785, 1)
                rows.append(row)
        enc = {
            "x": {"field": "x", "type": "quantitative",
                  "title": spec.get("x_label", "") or None, "scale": {"zero": False}},
            "y": {"field": "y", "type": "quantitative",
                  "title": spec.get("y_label", "") or None, "scale": {"zero": False}},
            "opacity": _OPACITY,
            "tooltip": [{"field": "x", "title": spec.get("x_label") or "x"},
                        {"field": "y", "title": spec.get("y_label") or "y"}],
        }
        if any(r["s"] for r in rows):
            enc["color"] = {"field": "s", "type": "nominal", "sort": None, "title": None}
        if sized:
            enc["size"] = {"field": "sz", "type": "quantitative",
                           "scale": None, "legend": None}
        points = {"mark": {"type": "point", "filled": True,
                           "size": 90 if not sized else None},
                  "encoding": enc}
        if not trend:
            return {"data": {"values": rows}, **points}
        trend_layer = {
            "data": {"values": [{"x": trend[0][0], "y": trend[0][1]},
                                {"x": trend[1][0], "y": trend[1][1]}]},
            "mark": {"type": "line", "strokeDash": [6, 4], "strokeWidth": 2,
                     "color": theme["palette"][2]},
            "encoding": {"x": {"field": "x", "type": "quantitative"},
                         "y": {"field": "y", "type": "quantitative"}},
        }
        return {"data": {"values": rows}, "layer": [points, trend_layer]}

    def _vl_scatter(self, spec, data, theme):
        return self._vl_points(spec, data, theme, sized=False)

    def _vl_bubble(self, spec, data, theme):
        return self._vl_points(spec, data, theme, sized=True)

    # — statistical / matrix —

    def _vl_box(self, spec, data, theme):
        rows = [{"g": g, "lo": st[0], "q1": st[1], "med": st[2],
                 "q3": st[3], "hi": st[4], "__ids": []}
                for g, st in zip(data.get("groups", []), data.get("stats", []))]
        x = {"field": "g", "type": "nominal", "sort": None,
             "title": spec.get("x_label", "") or None,
             "axis": {"labelAngle": -30}}
        y_title = spec.get("y_label", "") or None
        return {"data": {"values": rows}, "layer": [
            {"mark": {"type": "rule"},
             "encoding": {"x": x,
                          "y": {"field": "lo", "type": "quantitative",
                                "title": y_title, "scale": {"zero": False}},
                          "y2": {"field": "hi"}}},
            {"mark": {"type": "bar", "size": 26, "color": theme["palette"][0],
                      "stroke": theme["grid"]},
             "encoding": {"x": x,
                          "y": {"field": "q1", "type": "quantitative", "title": y_title},
                          "y2": {"field": "q3"},
                          "tooltip": [{"field": "g", "title": "group"},
                                      {"field": "lo", "title": "min"},
                                      {"field": "q1"}, {"field": "med"},
                                      {"field": "q3"}, {"field": "hi", "title": "max"}]}},
            {"mark": {"type": "tick", "size": 26, "thickness": 2,
                      "color": theme["palette"][2]},
             "encoding": {"x": x,
                          "y": {"field": "med", "type": "quantitative", "title": y_title}}},
        ]}

    # — uncertainty / distribution family —

    def _band_rows(self, data: dict) -> list[dict]:
        rows = []
        for s in data.get("series", []):
            name = s.get("name", "")
            ids = s.get("ids") or []
            for i, cat in enumerate(data.get("categories", [])):
                if i >= len(s.get("mean", [])) or s["mean"][i] is None:
                    continue
                rows.append({"c": cat, "s": name, "m": s["mean"][i],
                             "lo": s["lo"][i], "hi": s["hi"][i],
                             "__ids": ids[i] if i < len(ids) else []})
        return rows

    def _vl_errorband(self, spec, data, theme):
        rows = self._band_rows(data)
        multi = len(data.get("series", [])) > 1
        x = _axis_x(spec.get("x_label", ""))
        color = {"field": "s", "type": "nominal", "sort": None, "title": None}
        band = {"mark": {"type": "area", "opacity": 0.18, "interpolate": "monotone"},
                "encoding": {"x": x,
                             "y": {"field": "lo", "type": "quantitative",
                                   "title": spec.get("y_label", "") or None,
                                   "scale": {"zero": False}},
                             "y2": {"field": "hi"}}}
        line = {"mark": {"type": "line", "point": True, "strokeWidth": 2.5,
                         "interpolate": "monotone"},
                "encoding": {"x": x,
                             "y": {"field": "m", "type": "quantitative",
                                   "title": spec.get("y_label", "") or None},
                             "tooltip": [{"field": "c", "title": spec.get("x_label") or "category"},
                                         {"field": "m", "title": "mean"},
                                         {"field": "lo", "title": "-1σ"},
                                         {"field": "hi", "title": "+1σ"}]}}
        if multi:
            band["encoding"]["color"] = color
            line["encoding"]["color"] = dict(color)
        else:
            band["mark"]["color"] = theme["palette"][0]
            line["mark"]["color"] = theme["palette"][0]
        return {"data": {"values": rows}, "layer": [band, line]}

    def _vl_errorbar(self, spec, data, theme):
        rows = self._band_rows(data)
        multi = len(data.get("series", [])) > 1
        x = _axis_x(spec.get("x_label", ""))
        color = {"field": "s", "type": "nominal", "sort": None, "title": None}
        offset = {"field": "s", "sort": None}
        bar = {"mark": {"type": "bar"},
               "encoding": {"x": x,
                            "y": {"field": "m", "type": "quantitative",
                                  "title": spec.get("y_label", "") or None},
                            "tooltip": [{"field": "c", "title": spec.get("x_label") or "category"},
                                        {"field": "m", "title": "mean"},
                                        {"field": "lo", "title": "-1σ"},
                                        {"field": "hi", "title": "+1σ"}]}}
        rule = {"mark": {"type": "rule", "strokeWidth": 1.6, "color": theme["text"]},
                "encoding": {"x": x,
                             "y": {"field": "lo", "type": "quantitative",
                                   "title": spec.get("y_label", "") or None},
                             "y2": {"field": "hi"}}}
        if multi:
            bar["encoding"]["color"] = color
            bar["encoding"]["xOffset"] = offset
            rule["encoding"]["xOffset"] = dict(offset)
        else:
            bar["mark"]["color"] = theme["palette"][0]
        return {"data": {"values": rows}, "layer": [bar, rule]}

    def _vl_density(self, spec, data, theme):
        rows = []
        for s in data.get("series", []):
            for p in s.get("points", []):
                rows.append({"x": p[0], "d": p[1], "s": s.get("name", ""),
                             "__ids": []})
        multi = len(data.get("series", [])) > 1
        enc = {
            "x": {"field": "x", "type": "quantitative",
                  "title": spec.get("x_label", "") or None,
                  "scale": {"zero": False}},
            # stack=None: stacked areas impute 0 at every other series' grid
            # x, turning smooth KDE curves into a sawtooth
            "y": {"field": "d", "type": "quantitative", "title": "density",
                  "stack": None},
            "tooltip": [{"field": "x", "title": spec.get("x_label") or "x"},
                        {"field": "d", "title": "density", "format": ".4f"}],
        }
        mark = {"type": "area", "line": True, "opacity": 0.3,
                "interpolate": "monotone"}
        if multi:
            enc["color"] = {"field": "s", "type": "nominal", "sort": None,
                            "title": None}
        else:
            mark["color"] = theme["palette"][0]
        return {"data": {"values": rows}, "mark": mark, "encoding": enc}

    def _vl_violin(self, spec, data, theme):
        groups = data.get("groups", [])
        rows = []
        for i, g in enumerate(groups):
            poly = data.get("polygons", [])[i]
            half = len(poly) // 2
            # the polygon is left side + reversed right side: re-pair into
            # (xl, xr) per y sample for a ranged-area mark
            for j in range(half):
                left = poly[j]
                right = poly[len(poly) - 1 - j]
                rows.append({"g": g, "y": left[1], "xl": left[0], "xr": right[0],
                             "__ids": []})
        med_rows = [{"g": g, "x": i, "med": m, "__ids": []}
                    for i, (g, m) in enumerate(zip(groups,
                                                   data.get("medians", [])))]
        names = json.dumps(groups, ensure_ascii=False)
        x_axis = {"title": spec.get("x_label", "") or None, "grid": False,
                  "values": list(range(len(groups))),
                  "labelExpr": f"{names}[datum.value] || ''", "labelAngle": -30}
        return {"layer": [
            {"data": {"values": rows},
             "mark": {"type": "area", "opacity": 0.55, "interpolate": "monotone"},
             "encoding": {
                 "x": {"field": "xl", "type": "quantitative", "axis": x_axis,
                       "scale": {"domain": [-0.7, max(0.3, len(groups) - 0.3)]}},
                 "x2": {"field": "xr"},
                 # NO "order" channel here: with one, vega facets the path
                 # per order value and every violin degenerates to a 0-size
                 # path. Default y-sort is what a ranged area needs anyway.
                 "y": {"field": "y", "type": "quantitative",
                       "title": spec.get("y_label", "") or None,
                       "scale": {"zero": False}},
                 "color": {"field": "g", "type": "nominal", "sort": None,
                           "legend": None},
                 "tooltip": [{"field": "g", "title": "group"}],
             }},
            {"data": {"values": med_rows},
             "mark": {"type": "point", "filled": True, "size": 55,
                      "color": theme["text"]},
             "encoding": {
                 "x": {"field": "x", "type": "quantitative", "axis": x_axis,
                       "scale": {"domain": [-0.7, max(0.3, len(groups) - 0.3)]}},
                 "y": {"field": "med", "type": "quantitative",
                       "title": spec.get("y_label", "") or None},
                 "tooltip": [{"field": "g", "title": "group"},
                             {"field": "med", "title": "median"}],
             }},
        ]}

    def _vl_pareto(self, spec, data, theme):
        ids = data.get("ids") or [[]] * len(data.get("categories", []))
        rows = [{"c": c, "v": v, "cum": data.get("cum", [])[i],
                 "__ids": ids[i]}
                for i, (c, v) in enumerate(zip(data.get("categories", []),
                                               data.get("values", [])))]
        x = _axis_x(spec.get("x_label", ""))
        return {"data": {"values": rows},
                "resolve": {"scale": {"y": "independent"}},
                "layer": [
                    {"mark": {"type": "bar", "color": theme["palette"][0]},
                     "encoding": {
                         "x": x,
                         "y": {"field": "v", "type": "quantitative",
                               "title": spec.get("y_label", "") or None},
                         "opacity": _OPACITY,
                         "tooltip": [{"field": "c", "title": spec.get("x_label") or "category"},
                                     {"field": "v", "title": spec.get("y_label") or "value"},
                                     {"field": "cum", "title": "cumulative %"}]}},
                    {"mark": {"type": "line", "point": True, "strokeWidth": 2.5,
                              "color": theme["palette"][2 % len(theme["palette"])]},
                     "encoding": {
                         "x": dict(x),
                         "y": {"field": "cum", "type": "quantitative",
                               "title": "cumulative %",
                               "scale": {"domain": [0, 105]}}}},
                ]}

    def _vl_heatmap(self, spec, data, theme):
        vmin, vmax = data.get("vmin", 0), data.get("vmax", 1)
        mid = (vmin + vmax) / 2.0
        span = (vmax - vmin) or 1.0
        if data.get("diverging"):
            ramp = [theme["palette"][1], theme["bg"], theme["palette"][0]]
        else:
            ramp = [theme["bg"], theme["palette"][0], theme["palette"][2]]
        x_cats, y_cats = data.get("x_cats", []), data.get("y_cats", [])
        rows = []
        for xi, yi, v in data.get("cells", []):
            # white labels only where the ramp is dark (see echarts engine)
            if data.get("diverging"):
                intense = abs(v - mid) > span * 0.28
            else:
                intense = (v - vmin) > span * 0.72
            rows.append({"x": x_cats[xi], "y": y_cats[yi], "v": v,
                         "t": f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.3g}",
                         "__w": 1 if intense else 0,
                         "__ids": []})
        x = {"field": "x", "type": "nominal", "sort": None,
             "title": spec.get("x_label", "") or None, "axis": {"labelAngle": -30}}
        y = {"field": "y", "type": "nominal", "sort": None,
             "title": spec.get("y_label", "") or None}
        return {"data": {"values": rows}, "layer": [
            {"mark": {"type": "rect"},
             "encoding": {"x": x, "y": y,
                          "color": {"field": "v", "type": "quantitative",
                                    "scale": {"domain": [vmin, mid, vmax],
                                              "range": ramp},
                                    "title": None},
                          "tooltip": [{"field": "x"}, {"field": "y"},
                                      {"field": "v", "title": "value"}]}},
            # two fixed-colour text layers (white on intense cells, theme text
            # otherwise). A colour channel with scale:null would crash the
            # cross-layer scale merge in layered specs.
            {"transform": [{"filter": "datum.__w == 1"}],
             "mark": {"type": "text", "color": "#ffffff"},
             "encoding": {"x": x, "y": y, "text": {"field": "t"}}},
            {"transform": [{"filter": "datum.__w == 0"}],
             "mark": {"type": "text", "color": theme["text"]},
             "encoding": {"x": x, "y": y, "text": {"field": "t"}}},
        ]}
