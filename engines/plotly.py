# -*- coding: utf-8 -*-
"""Plotly engine — plotly.js (MIT) vendored in ../web/plotly.min.js."""
from __future__ import annotations

import json

from .base import ChartEngine, read_web, theme_of, wrap_html

_BODY = """
var gd = document.getElementById("chart");
Plotly.newPlot(gd, %(traces)s, %(layout)s, {responsive: true, displaylogo: false})
  .then(function () { window.__chartReady = true; });
gd.on("plotly_click", function (ev) {
  var ids = [];
  (ev.points || []).forEach(function (p) {
    if (p.customdata) ids = ids.concat(p.customdata);
  });
  if (ids.length) __o2vizSelect(ids);
});
"""


class PlotlyEngine(ChartEngine):
    id = "plotly"
    label = "Plotly"

    def build_html(self, spec: dict) -> str:
        traces, layout = self._figure(spec)
        body = _BODY % {"traces": json.dumps(traces, ensure_ascii=False),
                        "layout": json.dumps(layout, ensure_ascii=False)}
        return wrap_html(spec.get("title", ""), read_web("plotly.min.js"),
                         body, theme_of(spec))

    # ───────────────────── figure builder ─────────────────────

    def _figure(self, spec: dict):
        kind = spec["type"]
        data = spec.get("data", {})
        theme = theme_of(spec)
        layout: dict = {
            "title": {"text": spec.get("title", ""), "x": 0.5,
                      "font": {"color": theme["text"], "size": 16}},
            "colorway": theme["palette"],
            "paper_bgcolor": theme["bg"],
            "plot_bgcolor": theme["bg"],
            "font": {"color": theme["text"]},
            "margin": {"l": 70, "r": 30, "t": 60, "b": 70},
        }
        axis_style = {"gridcolor": theme["grid"], "linecolor": theme["grid"],
                      "zerolinecolor": theme["grid"]}

        def xy_layout():
            layout["xaxis"] = dict(axis_style, title={"text": spec.get("x_label", "")})
            layout["yaxis"] = dict(axis_style, title={"text": spec.get("y_label", "")})

        traces: list[dict] = []

        if kind in ("bar", "line", "area", "histogram"):
            xy_layout()
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
            xy_layout()
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
            traces.append({"type": "heatmap", "x": x_cats, "y": y_cats, "z": z,
                           "colorscale": [[0, theme["bg"]],
                                          [0.5, theme["palette"][0]],
                                          [1, theme["palette"][2]]],
                           "showscale": True})

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

        else:
            raise ValueError(f"Unsupported chart type: {kind}")

        return traces, layout
