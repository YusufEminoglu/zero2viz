# -*- coding: utf-8 -*-
"""One-click layer profiling: turn any layer into a full dashboard.

``build_profile(layer)`` inspects every field, decides what is worth
charting, computes plain-English insights and returns engine-ready chart
specs — all pure Python on top of core.datasource / stats / transform,
so the whole pipeline is testable headless.
"""
from __future__ import annotations

import re

from . import datasource, stats, transform

MAX_FIELDS = 30          # safety on very wide tables
MAX_CAT_CHARTS = 4       # bar charts for categorical fields
MAX_NUM_CHARTS = 6       # histograms for numeric fields
MAX_CATS_SHOWN = 12      # top-N per categorical bar
MAX_SCATTER_POINTS = 3000
HIST_BINS = 14

# Identifier-like field names carry no analytical meaning — a histogram of
# gid 1..N or a bar of unique uuids is pure noise on a dashboard. Skip them.
_ID_NAME_RE = re.compile(
    r"^(f?id|gid|oid|ogc_fid|object_?id|row_?id|pk\w*|uu?id|guid|"
    r"globalid|index)$|(_id|_fid|_oid|_uid|_uuid|_guid|_key|_pk)$",
    re.IGNORECASE,
)


def _is_id_name(name: str) -> bool:
    """True for fid / id / gid / uuid / objectid / *_id … style fields."""
    return bool(_ID_NAME_RE.search((name or "").strip()))


def _classify(values: list) -> str:
    """'numeric' | 'categorical' | 'skip' for one column of raw values."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "skip"
    floats = [v for v in (stats.to_float(x) for x in non_null) if v is not None]
    uniques = {str(v) for v in non_null}
    if len(floats) >= 0.6 * len(non_null) and len(uniques) > 8:
        return "numeric"
    if len(uniques) <= 30:
        # a category where every value occurs once (ids, names) is noise
        if len(uniques) == len(non_null) and len(non_null) > 6:
            return "skip"
        return "categorical"
    return "skip"


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def _fmt(v: float) -> str:
    """Human number formatting — no scientific notation in prose."""
    if abs(v) >= 10000:
        return f"{v:,.0f}"
    return f"{v:.4g}"


def build_profile(layer, selected_only: bool = False, theme: dict | None = None) -> dict:
    """→ {"title", "meta", "kpis", "insights", "tiles": [{"spec", "span"}]}"""
    field_names = [f.name() for f in layer.fields()][:MAX_FIELDS]
    cols, fids = datasource.columns_with_ids(layer, field_names, selected_only)
    n_rows = len(fids)

    # provider primary-key columns are identifiers by definition (GPKG fid,
    # PostGIS id…) even when their name doesn't look like one
    pk_names: set[str] = set()
    try:
        all_fields = layer.fields()
        pk_names = {all_fields[i].name() for i in layer.primaryKeyAttributes()}
    except Exception:
        pk_names = set()

    def _kind(name: str) -> str:
        if _is_id_name(name) or name in pk_names:
            return "skip"
        return _classify(cols[name])

    kinds = {name: _kind(name) for name in field_names}
    cat_fields = [n for n in field_names if kinds[n] == "categorical"]
    num_fields = [n for n in field_names if kinds[n] == "numeric"]

    tiles: list[dict] = []
    insights: list[str] = []

    def spec(kind, title, **kw):
        out = {"type": kind, "title": title, "x_label": kw.pop("x", ""),
               "y_label": kw.pop("y", ""), "stacked": False}
        if theme:
            out["theme"] = theme
        out.update(kw)
        return out

    # ── categorical fields → top-N count bars (clickable) ──
    for name in cat_fields[:MAX_CAT_CHARTS]:
        cats, vals, ids = transform.group_rows(cols[name], [], fids, "count")
        cats, vals, ids = transform.sort_cats(cats, vals, ids, "value_desc")
        cats, vals, ids = transform.topn_collapse(cats, vals, ids, MAX_CATS_SHOWN)
        tiles.append({"span": 1, "spec": spec(
            "bar", f"{name} — counts", x=name, y="count",
            data={"categories": cats,
                  "series": [{"name": "count", "values": vals, "ids": ids}]})})
        if cats and n_rows:
            insights.append(
                f"'{cats[0]}' is the largest {name} group "
                f"({int(vals[0])} of {n_rows} rows)")

    # ── numeric fields → histograms ──
    num_stats: dict[str, tuple] = {}
    for name in num_fields:
        finite = [v for v in (stats.to_float(x) for x in cols[name]) if v is not None]
        if finite:
            num_stats[name] = (min(finite), _mean(finite), max(finite))
    for name in num_fields[:MAX_NUM_CHARTS]:
        labels, counts = stats.histogram(cols[name], HIST_BINS)
        if not labels:
            continue
        lo, mean, hi = num_stats[name]
        tiles.append({"span": 1, "spec": spec(
            "histogram", f"{name} — distribution (mean {_fmt(mean)})",
            x=name, y="count", data={"categories": labels, "values": counts})})

    # ── correlations: matrix + strongest pair scatter ──
    best_pair, best_r = None, 0.0
    if len(num_fields) >= 2:
        x_cats = num_fields[:8]
        cells = []
        for i, a in enumerate(x_cats):
            for j, b in enumerate(x_cats):
                r = 1.0 if i == j else stats.pearson(cols[a], cols[b])
                if r is None:
                    continue
                cells.append([i, j, round(r, 2)])
                if i < j and abs(r) > abs(best_r):
                    best_pair, best_r = (a, b), r
        tiles.append({"span": 1, "spec": spec(
            "heatmap", "Correlation matrix (Pearson r)",
            data={"x_cats": x_cats, "y_cats": x_cats, "cells": cells,
                  "vmin": -1, "vmax": 1, "diverging": True})})
    if best_pair:
        a, b = best_pair
        points = []
        for i in range(min(n_rows, MAX_SCATTER_POINTS)):
            xf, yf = stats.to_float(cols[a][i]), stats.to_float(cols[b][i])
            if xf is not None and yf is not None:
                points.append([xf, yf, None, fids[i]])
        if points:
            tiles.append({"span": 1, "spec": spec(
                "scatter", f"{a} vs {b} (r = {best_r:.2f})", x=a, y=b,
                data={"series": [{"name": f"{a}/{b}", "points": points}],
                      "trend": transform.linreg_endpoints(points)})})
        verdict = ("strong" if abs(best_r) >= 0.7 else
                   "moderate" if abs(best_r) >= 0.4 else "weak")
        direction = "positive" if best_r > 0 else "negative"
        insights.insert(0, f"Strongest link: {a} ↔ {b} "
                           f"(r = {best_r:.2f}, {verdict} {direction})")

    # ── one numeric headline ──
    if num_stats:
        widest = max(num_stats, key=lambda k: (num_stats[k][2] - num_stats[k][0]))
        lo, mean, hi = num_stats[widest]
        insights.append(f"{widest} ranges {_fmt(lo)} – {_fmt(hi)} (mean {_fmt(mean)})")

    kpis = [("Rows", f"{n_rows:,}"),
            ("Fields", str(len(field_names))),
            ("Numeric", str(len(num_fields))),
            ("Categorical", str(len(cat_fields)))]

    return {"title": layer.name(),
            "meta": f"{n_rows:,} rows · {len(field_names)} fields"
                    + (" · selection only" if selected_only else ""),
            "kpis": kpis, "insights": insights[:5], "tiles": tiles}
