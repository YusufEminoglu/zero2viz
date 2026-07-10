# -*- coding: utf-8 -*-
"""Plotly engine — plotly.js (MIT) vendored in ../web/plotly.min.js."""
from __future__ import annotations

import json

from .base import ANIMATABLE, FONT_FAMILY, ChartEngine, read_web, theme_of, wrap_html

_BODY = """
var gd = document.getElementById("chart");
Plotly.newPlot(gd, %(traces)s, %(layout)s, {responsive: true, displaylogo: false})
  .then(function () {
    window.__chartReady = true;
    // re-fit once the embedded view settles (see base.py note on 0-height init)
    function __o2vizFit() { try { Plotly.Plots.resize(gd); } catch (e) {} }
    [60, 240, 600].forEach(function (ms) { setTimeout(__o2vizFit, ms); });
  });
gd.on("plotly_click", function (ev) {
  var ids = [];
  (ev.points || []).forEach(function (p) {
    if (p.customdata) ids = ids.concat(p.customdata);
  });
  if (ids.length) __o2vizSelect(ids);
});
// map → chart cross-filter via Plotly's native selection styling.
// Pie traces are skipped: plotly has no per-slice selectedpoints.
window.__o2vizHighlight = function (ids) {
  try {
    var want = null, i;
    if (ids && ids.length) {
      want = {};
      for (i = 0; i < ids.length; i++) want[ids[i]] = true;
    }
    var indices = [], traceIdx = [];
    (gd.data || []).forEach(function (tr, ti) {
      if (!tr.customdata || tr.type === "pie") return;
      traceIdx.push(ti);
      if (want === null) { indices.push(null); return; }
      var sel = [];
      tr.customdata.forEach(function (cd, pi) {
        for (var k = 0; k < (cd || []).length; k++) {
          if (want[cd[k]]) { sel.push(pi); return; }
        }
      });
      indices.push(sel);
    });
    if (traceIdx.length) {
      Plotly.restyle(gd, {"selectedpoints": indices,
                          "selected.marker.opacity": 1,
                          "unselected.marker.opacity": 0.16}, traceIdx);
    }
    window.__o2vizHighlighted = (want === null) ? -1 : ids.length;
  } catch (e) { /* highlight is guarded */ }
};
"""

# animated figure (play axis): data + layout + frames, with a slider and
# play/pause buttons baked into the layout. Cross-filter highlighting is
# disabled while animating (the frames already redraw the whole trace set).
_ANIM_BODY = """
var gd = document.getElementById("chart");
var FIG = {"data": %(data)s, "layout": %(layout)s, "frames": %(frames)s};
Plotly.newPlot(gd, FIG, {responsive: true, displaylogo: false}).then(function () {
  window.__o2vizFrameCount = (FIG.frames || []).length;
  window.__chartReady = true;
  function __o2vizFit() { try { Plotly.Plots.resize(gd); } catch (e) {} }
  [60, 240, 600].forEach(function (ms) { setTimeout(__o2vizFit, ms); });
});
gd.on("plotly_click", function (ev) {
  var ids = [];
  (ev.points || []).forEach(function (p) { if (p.customdata) ids = ids.concat(p.customdata); });
  if (ids.length) __o2vizSelect(ids);
});
window.__o2vizHighlight = function () { /* cross-filter paused during animation */ };
"""


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


class PlotlyEngine(ChartEngine):
    id = "plotly"
    label = "Plotly"
    animates = ANIMATABLE
    webkit_ok = False  # plotly.js is ES6+; the legacy QtWebKit fork can't parse it

    def build_html(self, spec: dict) -> str:
        if spec.get("frames") and spec["type"] in self.animates:
            traces, layout, frames = self._animated_figure(spec)
            body = _ANIM_BODY % {"data": json.dumps(traces, ensure_ascii=False),
                                 "layout": json.dumps(layout, ensure_ascii=False),
                                 "frames": json.dumps(frames, ensure_ascii=False)}
        else:
            traces, layout = self._figure(spec)
            body = _BODY % {"traces": json.dumps(traces, ensure_ascii=False),
                            "layout": json.dumps(layout, ensure_ascii=False)}
        return wrap_html(spec.get("title", ""), read_web("plotly.min.js"),
                         body, theme_of(spec))

    # ───────────────────────── animation (play axis) ─────────────────────────

    def _animated_figure(self, spec: dict):
        """→ (initial traces, layout with slider + play/pause, frames)."""
        frames = spec["frames"]
        static = {k: v for k, v in spec.items() if k != "frames"}
        labels = [str(x) for x in frames.get("labels", [])]
        interval = int(frames.get("interval", 900))
        trans = min(interval // 2, 400)

        traces, layout = self._figure(dict(static, data=frames["datas"][0]))
        self._fix_ranges(layout, spec["type"], frames.get("bounds"))

        pframes = []
        for i, fdata in enumerate(frames["datas"]):
            ftr, _ = self._figure(dict(static, data=fdata))
            pframes.append({"name": labels[i], "data": ftr})

        anim_args = {"mode": "immediate", "fromcurrent": True,
                     "frame": {"duration": interval, "redraw": True},
                     "transition": {"duration": trans}}
        pause_args = {"mode": "immediate", "frame": {"duration": 0, "redraw": False},
                      "transition": {"duration": 0}}
        steps = [{"label": lbl, "method": "animate",
                  "args": [[lbl], {"mode": "immediate",
                                   "frame": {"duration": interval, "redraw": True},
                                   "transition": {"duration": trans}}]}
                 for lbl in labels]
        field = frames.get("field", "")
        layout["sliders"] = [{
            "active": 0, "x": 0.08, "y": 0, "len": 0.92, "pad": {"t": 32, "b": 8},
            "currentvalue": {"prefix": f"{field}: " if field else "",
                             "font": {"size": 14}, "xanchor": "left"},
            "transition": {"duration": trans}, "steps": steps}]
        layout["updatemenus"] = [{
            "type": "buttons", "direction": "left", "showactive": False,
            "x": 0.08, "y": 0, "xanchor": "right", "yanchor": "top",
            "pad": {"t": 32, "r": 12},
            "buttons": [
                {"label": "▶", "method": "animate", "args": [None, anim_args]},
                {"label": "❚❚", "method": "animate", "args": [[None], pause_args]},
            ]}]
        layout["margin"]["b"] = max(layout["margin"].get("b", 72), 110)
        return traces, layout, pframes

    def _fix_ranges(self, layout: dict, kind: str, bounds) -> None:
        """Lock axis ranges to the global extent so frames don't rescale."""
        if not bounds:
            return

        def pad(rng, zero=False):
            lo, hi = rng
            if zero:
                lo = min(0.0, lo)
            span = (hi - lo) or abs(hi) or 1.0
            base = lo if (zero and lo == 0) else lo - span * 0.05
            return [base, hi + span * 0.05]

        if kind in ("scatter", "bubble"):
            if bounds.get("x"):
                layout["xaxis"]["range"] = pad(bounds["x"])
            if bounds.get("y"):
                layout["yaxis"]["range"] = pad(bounds["y"])
        elif kind in ("bar", "line", "area") and bounds.get("y"):
            layout["yaxis"]["range"] = pad(bounds["y"], zero=kind in ("bar", "area"))

    # ───────────────────── figure builder ─────────────────────

    def _figure(self, spec: dict):
        kind = spec["type"]
        data = spec.get("data", {})
        theme = theme_of(spec)
        dark = theme["bg"].lower() in ("#131c21",)
        layout: dict = {
            "title": {"text": spec.get("title", ""), "x": 0.5, "xanchor": "center",
                      "font": {"color": theme["text"], "size": 17,
                               "family": FONT_FAMILY}},
            "colorway": theme["palette"],
            "paper_bgcolor": theme["bg"],
            "plot_bgcolor": theme["bg"],
            "font": {"color": theme["text"], "family": FONT_FAMILY},
            "margin": {"l": 70, "r": 30, "t": 64, "b": 72},
            "hoverlabel": {"bgcolor": "#1b262c" if dark else "#ffffff",
                           "bordercolor": theme["grid"],
                           "font": {"color": theme["text"], "family": FONT_FAMILY}},
        }
        # faint dotted grid, no hard axis spikes — the Tableau-grade default
        axis_style = {"gridcolor": theme["grid"], "griddash": "dot",
                      "linecolor": theme["grid"], "zerolinecolor": theme["grid"],
                      "ticks": "outside", "tickcolor": theme["grid"]}

        def xy_layout(cat_x: bool = False):
            xa = dict(axis_style, title={"text": spec.get("x_label", "")})
            if cat_x:  # categorical x: drop vertical grid lines (chart junk)
                xa["showgrid"] = False
            layout["xaxis"] = xa
            layout["yaxis"] = dict(axis_style, title={"text": spec.get("y_label", "")})

        traces: list[dict] = []

        if kind in ("bar", "line", "area", "histogram"):
            xy_layout(cat_x=True)
            series_in = data.get("series") or [{"name": spec.get("y_label", "value"),
                                                "values": data.get("values", []),
                                                "ids": data.get("ids")}]
            for s in series_in:
                trace = {"name": s.get("name", ""), "x": data.get("categories", []),
                         "y": s.get("values", [])}
                if s.get("ids"):
                    trace["customdata"] = s["ids"]
                if kind in ("bar", "histogram"):
                    trace["type"] = "bar"
                else:
                    trace["type"] = "scatter"
                    trace["mode"] = "lines+markers"
                    trace["line"] = {"shape": "spline", "width": 2.5}
                if kind == "area":
                    if spec.get("stacked"):
                        trace["stackgroup"] = "one"
                    else:
                        trace["fill"] = "tozeroy"
                traces.append(trace)
            if kind == "bar":
                layout["barmode"] = "stack" if spec.get("stacked") else "group"
            if kind == "histogram":
                layout["bargap"] = 0.03

        elif kind in ("scatter", "bubble"):
            xy_layout()
            for s in data.get("series", []):
                xs, ys, sizes, ids = [], [], [], []
                for p in s.get("points", []):
                    xs.append(p[0])
                    ys.append(p[1])
                    sizes.append(p[2] if len(p) > 2 and p[2] is not None else 9)
                    ids.append([p[3]] if len(p) > 3 and p[3] is not None else [])
                traces.append({"type": "scatter", "mode": "markers",
                               "name": s.get("name", ""), "x": xs, "y": ys,
                               "customdata": ids,
                               "marker": {"size": sizes, "opacity": 0.78}})
            trend = data.get("trend")
            if trend:
                traces.append({"type": "scatter", "mode": "lines", "name": "trend",
                               "x": [trend[0][0], trend[1][0]],
                               "y": [trend[0][1], trend[1][1]],
                               "line": {"dash": "dash", "width": 2},
                               "hoverinfo": "skip"})

        elif kind == "pie":
            ids = data.get("ids") or [[]] * len(data.get("categories", []))
            traces.append({"type": "pie", "labels": data.get("categories", []),
                           "values": data.get("values", []), "hole": 0.45,
                           "customdata": ids,
                           "marker": {"line": {"color": theme["bg"], "width": 2}}})

        elif kind == "box":
            xy_layout(cat_x=True)
            groups = data.get("groups", [])
            stats = data.get("stats", [])
            traces.append({
                "type": "box", "x": groups, "name": spec.get("y_label", "value"),
                "lowerfence": [s[0] for s in stats], "q1": [s[1] for s in stats],
                "median": [s[2] for s in stats], "q3": [s[3] for s in stats],
                "upperfence": [s[4] for s in stats],
                "marker": {"color": theme["palette"][0]},
            })

        elif kind == "heatmap":
            xy_layout()
            x_cats = data.get("x_cats", [])
            y_cats = data.get("y_cats", [])
            z: list[list] = [[None] * len(x_cats) for _ in y_cats]
            for xi, yi, v in data.get("cells", []):
                z[yi][xi] = v
            if data.get("diverging"):
                scale = [[0, theme["palette"][1]], [0.5, theme["bg"]],
                         [1, theme["palette"][0]]]
            else:
                scale = [[0, theme["bg"]], [0.5, theme["palette"][0]],
                         [1, theme["palette"][2]]]
            traces.append({"type": "heatmap", "x": x_cats, "y": y_cats, "z": z,
                           "colorscale": scale, "showscale": True})

        elif kind in ("treemap", "sunburst"):
            ids_, labels, parents, values = [], [], [], []
            for node in data.get("nodes", []):
                ids_.append(node["name"])
                labels.append(node["name"])
                parents.append("")
                values.append(node["value"])
                for child in node.get("children", []):
                    ids_.append(f'{node["name"]}/{child["name"]}')
                    labels.append(child["name"])
                    parents.append(node["name"])
                    values.append(child["value"])
            traces.append({"type": kind, "ids": ids_, "labels": labels,
                           "parents": parents, "values": values,
                           "branchvalues": "total",
                           "marker": {"line": {"color": theme["bg"], "width": 1.5}}})

        elif kind in ("errorband", "errorbar"):
            xy_layout(cat_x=True)
            cats = data.get("categories", [])
            for si, s in enumerate(data.get("series", [])):
                color = theme["palette"][si % len(theme["palette"])]
                mean, lo, hi = s.get("mean", []), s.get("lo", []), s.get("hi", [])
                if kind == "errorband":
                    traces.append({"type": "scatter", "mode": "lines", "x": cats,
                                   "y": hi, "line": {"width": 0, "color": color},
                                   "hoverinfo": "skip", "showlegend": False})
                    traces.append({"type": "scatter", "mode": "lines", "x": cats,
                                   "y": lo, "line": {"width": 0, "color": color},
                                   "fill": "tonexty",
                                   "fillcolor": _rgba(color, 0.18),
                                   "hoverinfo": "skip", "showlegend": False})
                    traces.append({"type": "scatter", "mode": "lines+markers",
                                   "name": s.get("name", ""), "x": cats, "y": mean,
                                   "customdata": s.get("ids") or [],
                                   "line": {"color": color, "width": 2.5}})
                else:
                    traces.append({
                        "type": "bar", "name": s.get("name", ""), "x": cats,
                        "y": mean, "customdata": s.get("ids") or [],
                        "marker": {"color": color},
                        "error_y": {
                            "type": "data", "symmetric": False,
                            "array": [None if (h is None or mean[i] is None)
                                      else h - mean[i] for i, h in enumerate(hi)],
                            "arrayminus": [None if (l is None or mean[i] is None)
                                           else mean[i] - l for i, l in enumerate(lo)],
                            "color": theme["text"], "thickness": 1.6, "width": 5,
                        }})
            if kind == "errorbar":
                layout["barmode"] = "group"

        elif kind == "density":
            xy_layout()
            for si, s in enumerate(data.get("series", [])):
                color = theme["palette"][si % len(theme["palette"])]
                pts = s.get("points", [])
                traces.append({"type": "scatter", "mode": "lines",
                               "name": s.get("name", ""),
                               "x": [p[0] for p in pts], "y": [p[1] for p in pts],
                               "line": {"color": color, "width": 2,
                                        "shape": "spline"},
                               "fill": "tozeroy",
                               "fillcolor": _rgba(color, 0.3)})

        elif kind == "violin":
            xy_layout()
            groups = data.get("groups", [])
            medians = data.get("medians", [])
            for i, g in enumerate(groups):
                color = theme["palette"][i % len(theme["palette"])]
                poly = data.get("polygons", [])[i]
                traces.append({"type": "scatter", "mode": "lines", "name": g,
                               "x": [p[0] for p in poly] + [poly[0][0]],
                               "y": [p[1] for p in poly] + [poly[0][1]],
                               "fill": "toself", "fillcolor": _rgba(color, 0.45),
                               "line": {"color": color, "width": 1.2},
                               "hoverinfo": "name", "showlegend": False})
            traces.append({"type": "scatter", "mode": "markers", "name": "median",
                           "x": list(range(len(groups))), "y": medians,
                           "marker": {"color": theme["text"], "size": 7},
                           "hovertemplate": "median %{y}<extra></extra>",
                           "showlegend": False})
            layout["xaxis"]["tickvals"] = list(range(len(groups)))
            layout["xaxis"]["ticktext"] = groups
            layout["xaxis"]["range"] = [-0.7, len(groups) - 0.3]

        elif kind == "radar":
            axes = data.get("axes", [])
            maxes = data.get("maxes", []) or [1.0] * len(axes)
            for s in data.get("series", []):
                vals = s.get("values", [])
                # normalise per axis so mixed units share one polar scale
                r = [0 if (v is None or maxes[i] == 0) else v / maxes[i]
                     for i, v in enumerate(vals)]
                traces.append({"type": "scatterpolar",
                               "r": r + r[:1], "theta": axes + axes[:1],
                               "name": s.get("name", ""), "fill": "toself",
                               "opacity": 0.7,
                               "text": [f"{v:g}" if v is not None else ""
                                        for v in vals] + [""],
                               "hovertemplate": "%{theta}: %{text}<extra>%{fullData.name}</extra>"})
            layout["polar"] = {
                "bgcolor": theme["bg"],
                "radialaxis": {"visible": True, "range": [0, 1],
                               "showticklabels": False,
                               "gridcolor": theme["grid"]},
                "angularaxis": {"gridcolor": theme["grid"],
                                "linecolor": theme["grid"]},
            }

        elif kind == "pareto":
            xy_layout(cat_x=True)
            ids = data.get("ids") or [[]] * len(data.get("categories", []))
            traces.append({"type": "bar", "name": spec.get("y_label", "value"),
                           "x": data.get("categories", []),
                           "y": data.get("values", []), "customdata": ids,
                           "marker": {"color": theme["palette"][0]}})
            traces.append({"type": "scatter", "mode": "lines+markers",
                           "name": "cumulative %",
                           "x": data.get("categories", []),
                           "y": data.get("cum", []), "yaxis": "y2",
                           "line": {"color": theme["palette"][2 % len(theme["palette"])],
                                    "width": 2.5}})
            layout["yaxis2"] = dict(axis_style, overlaying="y", side="right",
                                    range=[0, 105], ticksuffix=" %",
                                    showgrid=False)
            layout["margin"]["r"] = 70
            layout["showlegend"] = False

        else:
            raise ValueError(f"Unsupported chart type: {kind}")

        return traces, layout
