# -*- coding: utf-8 -*-
"""Reference & statistics overlays — horizontal guide lines and shaded bands on
a chart's value axis, computed pure-Python from the plotted values.

A reader nearly always wants to know *where the numbers sit relative to
something*: the average, the middle, a target/threshold, the typical spread.
This module turns the values a chart already plots into a small list of
overlay dicts (mean / median line, a target line, a ±1σ band, an inter-quartile
band) that every engine renders identically — ECharts mark-lines/areas, Plotly
shapes, Vega-Lite rule/rect layers, matplotlib ``axhline``/``axhspan``.

It is deliberately Hub-safe and headless-testable: no qgis, no numpy, no I/O.
Everything is additive — a spec with no overlays renders exactly as before.
"""
from __future__ import annotations

from . import stats

# chart types whose value (Y) axis a horizontal reference line/band fits. Types
# with a categorical or non-value Y (pie, box, heatmap, treemap, radar, …) are
# excluded; the dock greys the controls out for them.
OVERLAY_TYPES = frozenset(("bar", "line", "area", "scatter", "bubble"))

# human labels for each overlay the UI offers
OVERLAY_LABELS = {
    "mean": "Mean", "median": "Median", "target": "Target",
    "sigma": "±1σ", "iqr": "IQR",
}


def chart_values(spec: dict) -> list[float]:
    """The numeric value-axis (Y) values a spec plots — the basis for the
    statistics. Bar/line/area flatten every series' values; scatter/bubble take
    each point's Y. Non-numeric entries are dropped."""
    kind = spec.get("type")
    data = spec.get("data", {})
    raw: list = []
    if kind in ("bar", "line", "area"):
        for series in data.get("series", []):
            raw.extend(series.get("values", []))
    elif kind in ("scatter", "bubble"):
        for series in data.get("series", []):
            for point in series.get("points", []):
                if len(point) > 1:
                    raw.append(point[1])
    return [v for v in (stats.to_float(x) for x in raw) if v is not None]


def _fmt(value: float) -> str:
    """Compact, human number for an overlay label (1,240 · 3.14 · 0.007)."""
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1000:
        return f"{value:,.0f}"
    return f"{value:.3g}"


def build_overlays(spec: dict, options: dict, theme: dict) -> list[dict]:
    """Compute the overlays for ``spec`` given the requested ``options``.

    ``options`` keys: ``mean``/``median``/``sigma``/``iqr`` (bool) and an
    optional numeric ``target``. Returns a list of overlay dicts the engines
    render, styled from ``theme`` so one call recolours every engine:

        {"kind": "line", "value": v, "label": str,
         "color": hex, "dash": [on, off], "width": px}
        {"kind": "band", "lo": lo, "hi": hi, "label": str,
         "color": hex, "opacity": 0..1}

    Bands come first so the lines draw on top of them. Returns ``[]`` when the
    type has no value axis, nothing is requested, or there is no numeric data —
    so callers can attach the result unconditionally.
    """
    if spec.get("type") not in OVERLAY_TYPES:
        return []
    values = chart_values(spec)
    if not values:
        return []

    text = theme.get("text", "#16323f")
    palette = theme.get("palette") or ["#2a8f85", "#fa8e7a"]
    accent = palette[1] if len(palette) > 1 else palette[0]

    mean_std = stats.mean_std(values)             # (mean, sample std) | None
    box = stats.boxplot_stats(values)             # [min, q1, med, q3, max] | None
    out: list[dict] = []

    # — bands (drawn under the lines) —
    if options.get("iqr") and box is not None:
        out.append({"kind": "band", "lo": box[1], "hi": box[3],
                    "label": OVERLAY_LABELS["iqr"],
                    "color": palette[0], "opacity": 0.12})
    if options.get("sigma") and mean_std is not None and mean_std[1] > 0:
        mean, std = mean_std
        out.append({"kind": "band", "lo": mean - std, "hi": mean + std,
                    "label": OVERLAY_LABELS["sigma"],
                    "color": text, "opacity": 0.09})

    # — lines (drawn over the bands) —
    if options.get("mean") and mean_std is not None:
        out.append({"kind": "line", "value": mean_std[0],
                    "label": f"{OVERLAY_LABELS['mean']} {_fmt(mean_std[0])}",
                    "color": text, "dash": [6, 4], "width": 1.7})
    if options.get("median") and box is not None:
        out.append({"kind": "line", "value": box[2],
                    "label": f"{OVERLAY_LABELS['median']} {_fmt(box[2])}",
                    "color": text, "dash": [2, 3], "width": 1.5})
    target = options.get("target")
    if target is not None:
        target = float(target)
        out.append({"kind": "line", "value": target,
                    "label": f"{OVERLAY_LABELS['target']} {_fmt(target)}",
                    "color": accent, "dash": [9, 3], "width": 2.0})
    return out
