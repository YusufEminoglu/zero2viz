# -*- coding: utf-8 -*-
"""ECharts engine — Apache ECharts (Apache-2.0) vendored in ../web/echarts.min.js."""
from __future__ import annotations

import json
import math

from .base import ANIMATABLE, FACETABLE, FONT_FAMILY, ChartEngine, read_web, theme_of, wrap_html

# chart types that carry reference lines/bands on their value axis (core.overlays)
_OVERLAY_OK = frozenset(("bar", "lollipop", "line", "area", "scatter", "bubble"))

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
// re-measure once the embedded view has settled its size (see base.py note):
// a single init can capture a 0-height container in QWebEngine and paint blank.
function __o2vizFit() { try { chart.resize(); } catch (e) {} }
window.addEventListener("resize", __o2vizFit);
if (window.requestAnimationFrame) requestAnimationFrame(__o2vizFit);
[60, 240, 600].forEach(function (ms) { setTimeout(__o2vizFit, ms); });
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
  } catch (e) { /* highlight is guarded */ }
};
// number of animation frames (0 = static chart) — read by the render harness
window.__o2vizFrameCount = (OPT.options && OPT.options.length) || 0;
// number of small-multiple panels (0 = single chart)
window.__o2vizFacetCount = OPT.__facets || 0;
window.__chartReady = true;
"""


def _tooltip(theme: dict, trigger: str = "item") -> dict:
    """A clean, card-like tooltip (soft shadow, rounded) shared by every
    chart — the small touches that read as publication-grade."""
    dark = theme["bg"].lower() in ("#131c21",)
    return {"trigger": trigger,
            "backgroundColor": "#1b262c" if dark else "#ffffff",
            "borderColor": theme["grid"], "borderWidth": 1,
            "textStyle": {"color": theme["text"], "fontFamily": FONT_FAMILY},
            "axisPointer": {"lineStyle": {"color": theme["grid"]},
                            "crossStyle": {"color": theme["grid"]}},
            "extraCssText": ("box-shadow:0 2px 12px rgba(0,0,0,0.14);"
                             "border-radius:7px;padding:8px 11px;")}


def _axis(theme: dict, name: str, kind: str = "value", data=None, rotate: int = 0,
          zero: bool = False) -> dict:
    ax = {"type": kind, "name": name, "nameLocation": "middle",
          "nameGap": 38 if kind == "category" else 46,
          "nameTextStyle": {"color": theme["text"], "fontFamily": FONT_FAMILY},
          "axisLabel": {"color": theme["text"], "fontFamily": FONT_FAMILY,
                        "hideOverlap": True},
          "axisLine": {"lineStyle": {"color": theme["grid"]}}}
    if kind == "category":
        ax["data"] = data or []
        # no vertical chart-junk lines; keep a subtle baseline + aligned ticks
        ax["splitLine"] = {"show": False}
        ax["axisTick"] = {"alignWithLabel": True, "lineStyle": {"color": theme["grid"]}}
        if rotate:
            ax["axisLabel"]["rotate"] = rotate
    else:
        # bars/areas must start at zero or relative sizes lie to the reader
        ax["scale"] = not zero
        # Tableau-style value axis: no axis line/ticks, faint dashed grid only
        ax["axisLine"] = {"show": False}
        ax["axisTick"] = {"show": False}
        ax["splitLine"] = {"lineStyle": {"color": theme["grid"],
                                         "type": "dashed", "opacity": 0.7}}
    return ax


def _nice_step(span: float, ticks: int = 5) -> float:
    """A 1 / 2 / 2.5 / 5 x 10^k tick step giving about ``ticks`` intervals."""
    raw = span / max(1, ticks)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= m * mag:
            return m * mag
    return 10.0 * mag


def _axis_fit(lo: float, hi: float) -> tuple[float, float, float]:
    """Pad a value range by 5 percent and snap both ends to a round tick
    step. → ``(lo, hi, step)``: pass ``step`` as the axis ``interval`` so the
    fixed ends are ticks too (no stray "5,855" or "14" label above the last
    gridline). A range that starts at or above zero is never padded below it."""
    span = (hi - lo) or abs(hi) or 1.0
    p_lo, p_hi = lo - span * 0.05, hi + span * 0.05
    if lo >= 0 > p_lo:
        p_lo = 0.0
    # every 1 / 2 / 2.5 / 5 x 10^k step giving 3-10 intervals (2 for integer
    # data); keep the one
    # that wastes the least range (ties: fewer ticks). Integer data (counts)
    # never gets a fractional step.
    integral = float(lo).is_integer() and float(hi).is_integer()
    top = math.floor(math.log10(p_hi - p_lo))
    best = None
    for k in range(top - 2, top + 2):
        for m in (1.0, 2.0, 2.5, 5.0):
            step = m * 10 ** k
            if integral and not float(step).is_integer():
                continue
            lo_n = math.floor(p_lo / step) * step
            hi_n = math.ceil(p_hi / step) * step
            n = round((hi_n - lo_n) / step)
            if (2 if integral else 3) <= n <= 10:
                key = ((hi_n - lo_n) - (p_hi - p_lo), n)
                if best is None or key < best[0]:
                    best = (key, lo_n, hi_n, step)
    if best is None:
        step = _nice_step(p_hi - p_lo, ticks=6)
        best = (None, math.floor(p_lo / step) * step, math.ceil(p_hi / step) * step, step)
    _key, lo_n, hi_n, step = best
    return round(lo_n, 10), round(hi_n, 10), step


def _padded_range(lo: float, hi: float) -> tuple[float, float]:
    """``(lo, hi)`` of :func:`_axis_fit`."""
    fit = _axis_fit(lo, hi)
    return fit[0], fit[1]


def _with_ids(values: list, ids: list | None) -> list:
    if not ids:
        return values
    return [{"value": v, "__ids": ids[i] if i < len(ids) else []}
            for i, v in enumerate(values)]


class EChartsEngine(ChartEngine):
    id = "echarts"
    label = "ECharts"
    animates = ANIMATABLE
    facets = FACETABLE

    def build_html(self, spec: dict) -> str:
        if spec.get("frames") and spec["type"] in self.animates:
            option = self._timeline_option(spec)
        elif spec.get("facets") and spec["type"] in self.facets:
            option = self._facet_option(spec)
        else:
            option = self.option(spec)
        return wrap_html(spec.get("title", ""), read_web("echarts.min.js"),
                         _BODY % {"option": json.dumps(option, ensure_ascii=False)},
                         theme_of(spec))

    def option(self, spec: dict) -> dict:
        """Public: the ECharts option for a spec (reused by the dashboard)."""
        return self._option(spec)

    # ───────────────────────── animation (timeline) ─────────────────────────

    def _timeline_option(self, spec: dict) -> dict:
        """Wrap the per-frame options in an ECharts ``timeline`` (play axis).

        Every frame is the ordinary single-chart option rebuilt for that
        frame's data; the baseOption holds the shared axes/title and a value
        axis fixed to the global range, so categories animate in place."""
        frames = spec["frames"]
        theme = theme_of(spec)
        static = {k: v for k, v in spec.items() if k != "frames"}

        base = self._option(static)  # spec["data"] is already frame 0 (union-aligned)
        self._stabilise_axes(base, spec["type"], frames.get("bounds"))
        if isinstance(base.get("grid"), dict):
            base["grid"]["bottom"] = max(base["grid"].get("bottom", 64), 96)

        labels = [str(x) for x in frames.get("labels", [])]
        field = frames.get("field", "")
        options = []
        for i, fdata in enumerate(frames["datas"]):
            opt = self._option(dict(static, data=fdata))
            entry = {"series": opt["series"]}
            if field:
                entry["title"] = {"subtext": f"{field}: {labels[i]}",
                                  "subtextStyle": {"color": theme["text"],
                                                   "fontSize": 13}}
            options.append(entry)

        accent = theme["palette"][0]
        base["timeline"] = {
            "show": True, "axisType": "category", "data": labels,
            "autoPlay": True, "loop": True, "rewind": False,
            "playInterval": int(frames.get("interval", 900)),
            "currentIndex": 0, "left": 30, "right": 30, "bottom": 8,
            "label": {"color": theme["text"], "fontFamily": FONT_FAMILY},
            "lineStyle": {"color": theme["grid"]},
            "itemStyle": {"color": theme["grid"]},
            "checkpointStyle": {"color": accent, "borderColor": accent},
            "controlStyle": {"color": theme["text"], "borderColor": theme["text"]},
            "progress": {"itemStyle": {"color": accent},
                         "lineStyle": {"color": accent}},
            "emphasis": {"controlStyle": {"color": accent, "borderColor": accent}},
        }
        if field:
            base.setdefault("title", {})["subtext"] = f"{field}: {labels[0]}"
        return {"baseOption": base, "options": options}

    # ───────────────────────── small multiples ─────────────────────────

    def _facet_option(self, spec: dict) -> dict:
        """One chart, one grid per panel (ECharts multi-grid).

        Every panel is the ordinary single-chart option for that panel's data,
        re-homed onto its own grid/axes. Series colours are pinned by series
        name and pie slices by category, so a colour means the same thing in
        every panel; value axes share the global range. All series live in
        one ``series`` array, so click-to-select and the map highlight keep
        working unchanged."""
        fac = spec["facets"]
        kind = spec["type"]
        theme = theme_of(spec)
        palette = theme["palette"] or ["#2a8f85"]
        static = {k: v for k, v in spec.items() if k != "facets"}
        datas = fac["datas"]
        labels = [str(v) for v in fac.get("labels", [])]
        n = len(datas)
        cols = max(1, min(n, int(fac.get("columns") or 1)))
        rows = -(-n // cols)

        base = self._option(dict(static, data=datas[0]))
        field = fac.get("field", "")
        dropped = fac.get("dropped") or []
        if dropped:
            base["title"]["subtext"] = (
                f"{len(dropped)} more {field} value{'s' if len(dropped) != 1 else ''} "
                f"not shown (smallest groups)")
            base["title"]["subtextStyle"] = {"color": theme["text"], "fontSize": 11}

        top, bottom, left, right = (15.0 if dropped else 12.0), 3.0, 2.0, 2.0
        cw = (100.0 - left - right) / cols
        ch = (100.0 - top - bottom) / rows
        head = min(4.0, ch * 0.18)   # panel title band
        pct = "{:.2f}%".format
        titles = [base["title"]]
        grids, xaxes, yaxes, series = [], [], [], []
        names: list[str] = []
        cats = fac.get("categories") or []

        for i, fdata in enumerate(datas):
            r, c = divmod(i, cols)
            x0, y0 = left + c * cw, top + r * ch
            titles.append({"text": labels[i] if i < len(labels) else "",
                           "left": pct(x0 + cw / 2), "top": pct(y0),
                           "textAlign": "center",
                           "textStyle": {"color": theme["text"], "fontSize": 12,
                                         "fontWeight": 600, "fontFamily": FONT_FAMILY}})
            opt = self._option(dict(static, data=fdata))
            if kind == "pie":
                for s in opt["series"]:
                    s.update(left=pct(x0), top=pct(y0 + head), width=pct(cw),
                             height=pct(ch - head), radius=["28%", "70%"],
                             label={"show": False})
                    for item in s.get("data", []):
                        j = cats.index(item["name"]) if item["name"] in cats else 0
                        item["itemStyle"] = {"color": palette[j % len(palette)]}
                    series.append(s)
                continue
            self._stabilise_axes(opt, kind, fac.get("bounds"))
            grids.append({"left": pct(x0 + 0.6), "top": pct(y0 + head),
                          "width": pct(cw - 1.2), "height": pct(ch - head - 1.0),
                          "containLabel": True})
            gi = len(grids) - 1
            xa, ya = dict(opt["xAxis"]), dict(opt["yAxis"])
            xa["gridIndex"] = ya["gridIndex"] = gi
            # axis titles on the outer panels only: less ink, same information
            if i + cols < n:
                xa["name"] = ""
            if c != 0:
                ya["name"] = ""
            xaxes.append(xa)
            yaxes.append(ya)
            for s in opt["series"]:
                nm = s.get("name", "")
                if nm not in names:
                    names.append(nm)
                col = palette[names.index(nm) % len(palette)]
                s["xAxisIndex"] = s["yAxisIndex"] = gi
                if s.get("stack"):
                    # ECharts stacks by id across ALL grids: keep panels apart
                    s["stack"] = f"{s['stack']}_{gi}"
                s["itemStyle"] = dict(s.get("itemStyle") or {}, color=col)
                series.append(s)

        base["title"] = titles
        base["series"] = series
        base["__facets"] = n
        if kind == "pie":
            base["legend"] = {"top": 30 if not dropped else 44, "type": "scroll",
                              "data": cats, "textStyle": {"color": theme["text"]}}
            for key in ("grid", "xAxis", "yAxis"):
                base.pop(key, None)
        else:
            base["grid"], base["xAxis"], base["yAxis"] = grids, xaxes, yaxes
            if len(names) > 1:
                base["legend"] = {"top": 30 if not dropped else 44, "type": "scroll",
                                  "data": names, "textStyle": {"color": theme["text"]}}
        return base

    def _stabilise_axes(self, option: dict, kind: str, bounds) -> None:
        """Fix the value axis (and, for scatter/bubble, both axes) to the
        global range so the chart doesn't rescale on every frame."""
        if not bounds:
            return
        if kind in ("scatter", "bubble"):
            for key, rng in (("xAxis", bounds.get("x")), ("yAxis", bounds.get("y"))):
                if rng and isinstance(option.get(key), dict):
                    lo, hi, step = _axis_fit(rng[0], rng[1])
                    option[key].update(min=lo, max=hi, interval=step, scale=False)
        elif bounds.get("y") and isinstance(option.get("yAxis"), dict):
            lo, hi = bounds["y"]
            if kind in ("bar", "lollipop", "area", "histogram"):
                lo = min(lo, 0.0)
            lo_p, hi_p, step = _axis_fit(lo, hi)
            option["yAxis"].update(min=lo_p, max=hi_p, interval=step, scale=False)

    # ───────────────────── option builder ─────────────────────

    def _option(self, spec: dict) -> dict:
        kind = spec["type"]
        data = spec.get("data", {})
        theme = theme_of(spec)
        option: dict = {
            "color": theme["palette"],
            "backgroundColor": theme["bg"],
            "textStyle": {"color": theme["text"], "fontFamily": FONT_FAMILY},
            "title": {"text": spec.get("title", ""), "left": "center",
                      "textStyle": {"color": theme["text"], "fontSize": 17,
                                    "fontWeight": 600, "fontFamily": FONT_FAMILY}},
            "tooltip": _tooltip(theme, "item"),
            "toolbox": {"feature": {"saveAsImage": {"name": "02viz_chart"},
                                    "dataZoom": {}, "restore": {}}},
        }
        grid = {"left": 64, "right": 30, "bottom": 64, "top": 72, "containLabel": False}

        if kind in ("bar", "line", "area", "histogram"):
            series_in = data.get("series") or [{"name": spec.get("y_label", "value"),
                                                "values": data.get("values", []),
                                                "ids": data.get("ids")}]
            option["tooltip"] = _tooltip(theme, "axis")
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
                    item["lineStyle"] = {"width": 2.6}
                if kind == "area":
                    item["areaStyle"] = {"opacity": 0.32}
                if spec.get("stacked") and kind in ("bar", "area"):
                    item["stack"] = "total"
                # subtle rounded bar tops read as polished, not default-library
                if kind in ("bar", "histogram") and not spec.get("stacked"):
                    item["itemStyle"] = {"borderRadius": [4, 4, 0, 0]}
                out.append(item)
            option["series"] = out

        elif kind == "lollipop":
            series_in = data.get("series") or [{"name": spec.get("y_label", "value"),
                                                "values": data.get("values", []),
                                                "ids": data.get("ids")}]
            option["tooltip"] = _tooltip(theme, "axis")
            option["grid"] = grid
            option["xAxis"] = _axis(theme, spec.get("x_label", ""), "category",
                                    data.get("categories", []), rotate=30)
            option["yAxis"] = _axis(theme, spec.get("y_label", ""), zero=True)
            if len(series_in) > 1:
                option["legend"] = {"top": 28, "textStyle": {"color": theme["text"]},
                                    "data": [s.get("name", "") for s in series_in]}
            out = []
            for si, s in enumerate(series_in):
                color = theme["palette"][si % len(theme["palette"])]
                pts = _with_ids(s.get("values", []), s.get("ids"))
                out.append({
                    "name": f"{s.get('name', '')}·stem", "type": "bar",
                    "barWidth": 3, "data": pts,
                    "itemStyle": {"color": color, "opacity": 0.75,
                                  "borderRadius": [2, 2, 0, 0]},
                    "tooltip": {"show": False},
                })
                out.append({
                    "name": s.get("name", ""), "type": "scatter",
                    "symbolSize": 12, "data": pts, "z": 3,
                    "itemStyle": {"color": color, "borderColor": theme["bg"],
                                  "borderWidth": 1.5},
                })
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
            option["tooltip"] = _tooltip(theme, "axis")
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

        elif kind == "ecdf":
            option["tooltip"] = _tooltip(theme, "axis")
            option["grid"] = grid
            option["xAxis"] = _axis(theme, spec.get("x_label", ""))
            pct_axis = _axis(theme, "cumulative %", zero=True)
            pct_axis.update(min=0, max=100)
            pct_axis["axisLabel"]["formatter"] = "{value} %"
            option["yAxis"] = pct_axis
            series_in = data.get("series", [])
            if len(series_in) > 1:
                option["legend"] = {"top": 28, "textStyle": {"color": theme["text"]}}
            option["series"] = [
                {"name": s.get("name", ""), "type": "line", "step": "end",
                 "data": s.get("points", []),
                 "showSymbol": len(s.get("points", [])) <= 30, "symbolSize": 5,
                 "lineStyle": {"width": 2.5}}
                for s in series_in
            ]

        elif kind == "lorenz":
            option["tooltip"] = _tooltip(theme, "axis")
            option["grid"] = grid
            x_ax = _axis(theme, "cumulative share of features (%)", zero=True)
            x_ax.update(min=0, max=100)
            y_ax = _axis(theme, f"cumulative share of {spec.get('x_label') or 'value'} (%)", zero=True)
            y_ax.update(min=0, max=100)
            option["xAxis"] = x_ax
            option["yAxis"] = y_ax
            series_in = data.get("series", [])
            option["legend"] = {"top": 28, "textStyle": {"color": theme["text"]}}
            out = [{
                "name": "equality (G = 0)", "type": "line",
                "data": [[0.0, 0.0], [100.0, 100.0]],
                "showSymbol": False, "silent": True,
                "lineStyle": {"type": "dashed", "width": 1.6, "color": theme["text"],
                              "opacity": 0.45},
                "itemStyle": {"color": theme["text"]},
                "tooltip": {"show": False},
            }]
            for si, s in enumerate(series_in):
                color = theme["palette"][si % len(theme["palette"])]
                g = s.get("gini", 0.0)
                lbl = f"{s.get('name', '')} (Gini = {g:.3f})"
                out.append({
                    "name": lbl, "type": "line",
                    "data": s.get("points", []), "smooth": True,
                    "showSymbol": False,
                    "lineStyle": {"width": 2.6, "color": color},
                    "itemStyle": {"color": color},
                    "areaStyle": {"color": color,
                                  "opacity": 0.16 if len(series_in) == 1 else 0.08},
                })
            option["series"] = out

        else:
            raise ValueError(f"Unsupported chart type: {kind}")

        if spec.get("overlays") and kind in _OVERLAY_OK:
            self._add_overlays(option, spec["overlays"], theme)
        return option

    def _add_overlays(self, option: dict, overlays: list, theme: dict) -> None:
        """Reference lines/bands (see core.overlays) as invisible carrier
        series: a low-z series holds the markAreas (bands sit behind the data)
        and a high-z series the markLines (guides sit on top)."""
        mark_lines, mark_areas = [], []
        for ov in overlays:
            if ov.get("kind") == "line":
                mark_lines.append({
                    "yAxis": ov["value"],
                    "lineStyle": {"color": ov.get("color"),
                                  "type": ov.get("dash") or "dashed",
                                  "width": ov.get("width", 1.6)},
                    "label": {"show": True, "formatter": ov.get("label", ""),
                              "position": "insideEndTop", "color": ov.get("color"),
                              "fontFamily": FONT_FAMILY, "fontSize": 11},
                })
            else:
                mark_areas.append([
                    {"yAxis": ov["lo"],
                     "itemStyle": {"color": ov.get("color"),
                                   "opacity": ov.get("opacity", 0.12)},
                     "label": {"show": True, "formatter": ov.get("label", ""),
                               "position": "insideTopLeft", "color": ov.get("color"),
                               "fontFamily": FONT_FAMILY, "fontSize": 10}},
                    {"yAxis": ov["hi"]},
                ])
        # keep the legend to the real series (carriers must not show up there)
        real_names = [s.get("name", "") for s in option.get("series", [])
                      if s.get("name")]
        base = {"type": "line", "data": [], "silent": True, "showSymbol": False,
                "legendHoverLink": False, "tooltip": {"show": False}}
        if mark_areas:
            option["series"].append(dict(base, name="reference-band", z=0,
                                         markArea={"silent": True, "data": mark_areas}))
        if mark_lines:
            option["series"].append(dict(
                base, name="reference", z=6,
                markLine={"symbol": "none", "silent": True, "animation": False,
                          "data": mark_lines}))
        legend = option.get("legend")
        if isinstance(legend, dict) and "data" not in legend and real_names:
            legend["data"] = real_names
