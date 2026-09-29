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
  details.fields {{ background: {card}; border: 1px solid {grid}; border-radius: 12px;
                    padding: 6px 16px 14px; margin: 0 0 18px; }}
  details.fields > summary {{ cursor: pointer; font-weight: 600; padding: 8px 0;
                              font-size: 14px; list-style: none; }}
  details.fields > summary::-webkit-details-marker {{ display: none; }}
  details.fields > summary::before {{ content: "▸ "; color: {accent}; }}
  details.fields[open] > summary::before {{ content: "▾ "; }}
  table.fields {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table.fields th {{ text-align: left; color: {muted}; font-weight: 600;
                     padding: 6px 10px; border-bottom: 1px solid {grid};
                     text-transform: uppercase; font-size: 11px; letter-spacing: 0.6px; }}
  table.fields td {{ padding: 6px 10px; border-bottom: 1px solid {grid}; }}
  table.fields tr:last-child td {{ border-bottom: 0; }}
  .pill {{ font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 999px; }}
  .pill.numeric {{ background: rgba(42,143,133,0.16); color: {accent}; }}
  .pill.categorical {{ background: rgba(244,162,97,0.18); color: #b9701f; }}
  .pill.id, .pill.text {{ background: rgba(141,153,174,0.18); color: {muted}; }}
  .miss-ok {{ color: {muted}; }}
  .miss-hi {{ color: #d6604d; font-weight: 600; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
           gap: 14px; }}
  .tile {{ background: {card}; border: 1px solid {grid}; border-radius: 12px;
           padding: 6px; min-height: 340px; }}
  .chart {{ width: 100%; height: 336px; }}
  .play {{ position: sticky; top: 0; z-index: 5; display: flex; align-items: center;
           gap: 12px; background: {card}; border: 1px solid {grid}; border-radius: 12px;
           padding: 8px 14px; margin: 0 0 14px; }}
  .play button {{ border: 0; border-radius: 999px; width: 34px; height: 34px;
                  background: {accent}; color: #ffffff; font-size: 14px; cursor: pointer; }}
  .play input[type=range] {{ flex: 1; accent-color: {accent}; }}
  .play .flabel {{ min-width: 140px; font-weight: 600; font-size: 14px; }}
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
  {play_bar}
  {fields_table}
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
  }} catch (e) {{ /* highlight is guarded */ }}
}};
// Explore animation: one shared play axis steps every animated tile and the
// KPI cards together. FRAMES is null for a static dashboard.
var FRAMES = {frames};
window.__o2vizFrameCount = FRAMES ? FRAMES.labels.length : 0;
if (FRAMES) {{
  var slider = document.getElementById("o2vizSlider");
  var btn = document.getElementById("o2vizPlayBtn");
  var flabel = document.getElementById("o2vizFrameLabel");
  var kpiEls = document.querySelectorAll(".kpi .v");
  var timer = null;
  window.__o2vizSetFrame = function (k) {{
    k = ((k % FRAMES.labels.length) + FRAMES.labels.length) % FRAMES.labels.length;
    slider.value = k;
    flabel.textContent = FRAMES.field + ": " + FRAMES.labels[k];
    for (var ci = 0; ci < CHARTS.length; ci++) {{
      var fs = FRAMES.tiles[ci];
      if (!fs) continue;
      OPTIONS[ci].series = JSON.parse(JSON.stringify(fs[k]));
      CHARTS[ci].setOption({{ series: OPTIONS[ci].series }});
    }}
    var kv = FRAMES.kpis[k] || [];
    for (var j = 0; j < kpiEls.length && j < kv.length; j++) kpiEls[j].textContent = kv[j];
    window.__o2vizFrame = k;
  }};
  function stop() {{ if (timer) {{ clearInterval(timer); timer = null; }} btn.textContent = "\u25B6"; }}
  function play() {{
    stop();
    btn.textContent = "\u275A\u275A";
    timer = setInterval(function () {{ window.__o2vizSetFrame(window.__o2vizFrame + 1); }},
                        FRAMES.interval);
  }}
  btn.addEventListener("click", function () {{ if (timer) stop(); else play(); }});
  slider.addEventListener("input", function () {{ stop(); window.__o2vizSetFrame(+slider.value); }});
  window.__o2vizSetFrame(0);
  play();
}}
window.__chartCount = OPTIONS.length;
window.__chartReady = true;
</script>
</body>
</html>
"""


def _card_color(theme: dict) -> str:
    # a card surface slightly off the page background
    return "#1b262c" if theme["bg"].lower() in ("#131c21",) else "#ffffff"


def _fields_table(field_rows: list, esc) -> str:
    """A collapsible <details> table: field · type · missing % · distinct ·
    summary. Returns '' when the profile carries no field rows."""
    if not field_rows:
        return ""
    body = []
    for f in field_rows:
        miss = f.get("missing", 0.0)
        cls = "miss-hi" if miss >= 30.0 else "miss-ok"
        body.append(
            f'<tr><td><b>{esc(str(f.get("name", "")))}</b></td>'
            f'<td><span class="pill {esc(str(f.get("type", "")))}">'
            f'{esc(str(f.get("type", "")))}</span></td>'
            f'<td class="{cls}">{miss:g}%</td>'
            f'<td>{f.get("distinct", 0):,}</td>'
            f'<td>{esc(str(f.get("summary", "")))}</td></tr>')
    return (
        f'<details class="fields"><summary>Field summary — {len(field_rows)} '
        f'fields (type · missing · distinct · range/top)</summary>'
        f'<table class="fields"><thead><tr><th>Field</th><th>Type</th>'
        f'<th>Missing</th><th>Distinct</th><th>Summary</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></details>')


def build_dashboard(profile: dict, theme: dict | None = None) -> str:
    theme = theme or THEMES[DEFAULT_THEME]
    esc = html_escape.escape

    engine = EChartsEngine()
    frames = profile.get("frames")
    options = []
    tile_frames = []
    for tile in profile["tiles"]:
        spec = dict(tile["spec"])
        spec["theme"] = theme
        tf = tile.get("frames") if frames else None
        if tf:
            spec["data"] = tf["datas"][0]
        option = engine.option(spec)
        option["toolbox"] = {"show": False}  # tiles stay clean; export is page-level
        option.setdefault("title", {}).setdefault("textStyle", {})["fontSize"] = 14
        if tf:
            # fixed axes: bars and points move, the frame of reference does not
            engine._stabilise_axes(option, spec["type"], tf.get("bounds"))
            tile_frames.append([engine.option(dict(spec, data=d))["series"]
                                for d in tf["datas"]])
        else:
            tile_frames.append(None)
        options.append(option)

    play_bar = ""
    frames_json = "null"
    if frames:
        n = len(frames["labels"])
        play_bar = (
            '<div class="play"><button id="o2vizPlayBtn" title="Play / pause">&#9654;</button>'
            f'<input type="range" id="o2vizSlider" min="0" max="{n - 1}" value="0" step="1">'
            '<span class="flabel" id="o2vizFrameLabel"></span></div>')
        frames_json = json.dumps({
            "field": frames["field"], "labels": [str(v) for v in frames["labels"]],
            "interval": int(frames.get("interval", 1400)),
            "kpis": frames.get("kpis") if profile.get("kpis") else [],
            "tiles": tile_frames}, ensure_ascii=False)

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
        fields_table=_fields_table(profile.get("fields", []), esc),
        tiles=tiles_html,
        play_bar=play_bar,
        frames=frames_json,
        options=json.dumps(options, ensure_ascii=False),
        lib=read_web("echarts.min.js"),
        bridge=BRIDGE_JS,
        bg=theme["bg"], text=theme["text"], grid=theme["grid"],
        card=_card_color(theme),
        muted="#8d99ae" if theme["bg"] != "#131c21" else "#7d97a5",
        accent=theme["palette"][0], accent2=theme["palette"][1],
    )
