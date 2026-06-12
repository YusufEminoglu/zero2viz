# -*- coding: utf-8 -*-
"""Dashboard composer: a layer profile → one self-contained HTML page.

Header (title, meta, insight bullets) + KPI cards + a responsive grid of
interactive ECharts tiles. Same selection bridge as single charts, so
every bar and point still selects features on the canvas.
"""
from __future__ import annotations

import html as html_escape
import json

from .base import BRIDGE_JS, DEFAULT_THEME, THEMES, read_web
from .echarts import EChartsEngine

_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: {bg}; color: {text};
               font-family: "Segoe UI", system-ui, sans-serif; }}
  .wrap {{ max-width: 1480px; margin: 0 auto; padding: 22px 26px 34px; }}
  header h1 {{ margin: 0; font-size: 26px; letter-spacing: 0.2px; }}
  header h1 .brand {{ color: {accent}; }}
  .meta {{ margin-top: 4px; color: {muted}; font-size: 13px; }}
  ul.insights {{ margin: 14px 0 0; padding: 0; list-style: none; }}
  ul.insights li {{ display: inline-block; background: {card}; border: 1px solid {grid};
                    border-radius: 999px; padding: 6px 14px; margin: 0 8px 8px 0;
                    font-size: 13px; }}
  ul.insights li::before {{ content: "◆ "; color: {accent2}; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
           gap: 12px; margin: 18px 0; }}
  .kpi {{ background: {card}; border: 1px solid {grid}; border-radius: 12px;
          padding: 14px 16px; }}
  .kpi .v {{ font-size: 24px; font-weight: 700; color: {accent}; }}
  .kpi .l {{ font-size: 12px; color: {muted}; margin-top: 2px;
             text-transform: uppercase; letter-spacing: 0.8px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
           gap: 14px; }}
  .tile {{ background: {card}; border: 1px solid {grid}; border-radius: 12px;
           padding: 6px; min-height: 340px; }}
  .chart {{ width: 100%; height: 336px; }}
  footer {{ margin-top: 18px; color: {muted}; font-size: 12px; text-align: center; }}
</style>
<script>{lib}</script>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="brand">02viz</span> · {title}</h1>
    <div class="meta">{meta}</div>
    <ul class="insights">{insights}</ul>
  </header>
  <div class="kpis">{kpis}</div>
  <div class="grid">{tiles}</div>
  <footer>built with 02viz — Geospatial Visualization Studio · charts are interactive, clicks select features in QGIS</footer>
</div>
<script>
{bridge}
var OPTIONS = {options};
var CHARTS = [];
var els = document.querySelectorAll(".chart");
for (var i = 0; i < els.length; i++) {{
  (function (el, opt) {{
    var c = echarts.init(el, null, {{ renderer: "canvas" }});
    c.setOption(opt);
    CHARTS.push(c);
    c.on("click", function (p) {{
      var ids = p.data && p.data.__ids;
      if (ids && ids.length) __o2vizSelect(ids);
    }});
    window.addEventListener("resize", function () {{ c.resize(); }});
  }})(els[i], OPTIONS[i]);
}}
// map → chart cross-filter: dim items whose features are not selected.
window.__o2vizHighlight = function (ids) {{
  try {{
    var want = null, i;
    if (ids && ids.length) {{
      want = {{}};
      for (i = 0; i < ids.length; i++) want[ids[i]] = true;
    }}
    for (var ci = 0; ci < CHARTS.length; ci++) {{
      var opt = OPTIONS[ci], touched = false, series = opt.series || [];
      for (var si = 0; si < series.length; si++) {{
        var d = series[si].data || [];
        for (var di = 0; di < d.length; di++) {{
          var it = d[di];
          if (!it || it.constructor !== Object || !it.__ids || !it.__ids.length) continue;
          it.itemStyle = it.itemStyle || {{}};
          if (want === null) {{
            delete it.itemStyle.opacity;
          }} else {{
            var hit = false;
            for (i = 0; i < it.__ids.length; i++) if (want[it.__ids[i]]) {{ hit = true; break; }}
            it.itemStyle.opacity = hit ? 1 : 0.16;
          }}
          touched = true;
        }}
      }}
      if (touched) CHARTS[ci].setOption(opt, true);
    }}
    window.__o2vizHighlighted = (want === null) ? -1 : ids.length;
  }} catch (e) {{ /* highlight is best-effort */ }}
}};
window.__chartCount = OPTIONS.length;
window.__chartReady = true;
</script>
</body>
</html>
"""


def _card_color(theme: dict) -> str:
    # a card surface slightly off the page background
    return "#1b262c" if theme["bg"].lower() in ("#131c21",) else "#ffffff"


def build_dashboard(profile: dict, theme: dict | None = None) -> str:
    theme = theme or THEMES[DEFAULT_THEME]
    esc = html_escape.escape

    engine = EChartsEngine()
    options = []
    for tile in profile["tiles"]:
        spec = dict(tile["spec"])
        spec["theme"] = theme
        option = engine.option(spec)
        option["toolbox"] = {"show": False}  # tiles stay clean; export is page-level
        option.setdefault("title", {}).setdefault("textStyle", {})["fontSize"] = 14
        options.append(option)

    kpi_html = "".join(
        f'<div class="kpi"><div class="v">{esc(str(v))}</div>'
        f'<div class="l">{esc(str(label))}</div></div>'
        for label, v in profile.get("kpis", []))
    insight_html = "".join(f"<li>{esc(s)}</li>" for s in profile.get("insights", []))
    tiles_html = "".join('<div class="tile"><div class="chart"></div></div>'
                         for _ in options)

    return _PAGE.format(
        title=esc(profile.get("title", "")),
        meta=esc(profile.get("meta", "")),
        insights=insight_html,
        kpis=kpi_html,
        tiles=tiles_html,
        options=json.dumps(options, ensure_ascii=False),
        lib=read_web("echarts.min.js"),
        bridge=BRIDGE_JS,
        bg=theme["bg"], text=theme["text"], grid=theme["grid"],
        card=_card_color(theme),
        muted="#8d99ae" if theme["bg"] != "#131c21" else "#7d97a5",
        accent=theme["palette"][0], accent2=theme["palette"][1],
    )
