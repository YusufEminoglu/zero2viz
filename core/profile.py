# -*- coding: utf-8 -*-
"""One-click layer profiling: turn any layer into a full dashboard.

``build_profile(layer)`` inspects every field, decides what is worth
charting, computes plain-English insights and returns engine-ready chart
specs — all pure Python on top of core.datasource / stats / transform,
so the whole pipeline is testable headless.
"""
from __future__ import annotations

from . import datasource, fields, stats, transform

MAX_FIELDS = 30          # safety on very wide tables
MAX_CAT_CHARTS = 4       # bar charts for categorical fields
MAX_NUM_CHARTS = 6       # histograms for numeric fields
MAX_CATS_SHOWN = 12      # top-N per categorical bar
MAX_SCATTER_POINTS = 3000
SECTION_NAMES = ("kpis", "fields", "count_bars", "histograms", "corr_matrix", "scatter_trend", "normalised_box", "insights")
HIST_BINS = 14


def _fmt(v: float) -> str:
    """Human number formatting — no scientific notation in prose."""
    if abs(v) >= 10000:
        return f"{v:,.0f}"
    return f"{v:.4g}"


def build_profile(layer, selected_only: bool = False, theme: dict | None = None,
                  sections: list[str] | set[str] | None = None,
                  animate_by: str = "", interval: int = 1400) -> dict:
    """→ {"title", "meta", "kpis", "insights", "tiles": [{"spec", "span"}],
    "frames"}; "frames" is None unless ``animate_by`` names a field with at
    least two values.

    With ``animate_by`` every count-bar, histogram and scatter tile gets a
    per-frame ``tile["frames"]`` on the whole-layer axis (same categories,
    same bin edges, same scatter bounds), and the Rows / Complete KPIs get
    a value per frame; the correlation matrix and box plot stay static."""
    wanted = set(SECTION_NAMES if sections is None else sections)
    field_names = [f.name() for f in layer.fields()][:MAX_FIELDS]
    all_names = {f.name() for f in layer.fields()}
    animate_by = animate_by if animate_by in all_names else ""
    extract = field_names + (
        [animate_by] if animate_by and animate_by not in field_names else [])
    cols, fids, extraction = datasource.columns_with_ids_info(
        layer, extract, selected_only)
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
        if fields.is_id_name(name) or name in pk_names:
            return "skip"
        return fields.classify(cols[name])

    kinds = {name: _kind(name) for name in field_names}
    if animate_by in kinds:
        kinds[animate_by] = "skip"  # the play axis is not also profiled as data
    cat_fields = [n for n in field_names if kinds[n] == "categorical"]
    num_fields = [n for n in field_names if kinds[n] == "numeric"]

    # full numeric summary per field (min/max/mean/std) — drives the field
    # table, the normalised comparison and several insights
    num_stats: dict[str, dict] = {}
    for name in num_fields:
        st = stats.field_numeric_stats(cols[name])
        if st:
            num_stats[name] = st

    tiles: list[dict] = []
    insights: list[str] = []

    def spec(kind, title, **kw):
        out = {"type": kind, "title": title, "x_label": kw.pop("x", ""),
               "y_label": kw.pop("y", ""), "stacked": False}
        if theme:
            out["theme"] = theme
        out.update(kw)
        return out

    # ── per-field summary table + data-quality scan ──
    field_rows: list[dict] = []
    filled_cells = 0
    high_null: list[str] = []
    for name in field_names:
        col = cols[name]
        non_null = [v for v in col if v is not None]
        filled_cells += len(non_null)
        missing_pct = 100.0 * (n_rows - len(non_null)) / n_rows if n_rows else 0.0
        if missing_pct >= 30.0:
            high_null.append(name)
        distinct = len({str(v) for v in non_null})
        kind = kinds[name]
        if fields.is_id_name(name) or name in pk_names:
            ktype, summary = "id", "identifier"
        elif kind == "numeric" and name in num_stats:
            st = num_stats[name]
            ktype = "numeric"
            summary = f"{_fmt(st['min'])} … {_fmt(st['mean'])} … {_fmt(st['max'])}"
        elif kind == "categorical":
            ktype = "categorical"
            cats, vals, _ = transform.group_rows(col, [], fids, "count")
            if cats:
                top = max(range(len(cats)), key=lambda i: vals[i])
                summary = f"top “{cats[top]}” · {distinct} distinct"
            else:
                summary = f"{distinct} distinct"
        else:
            ktype = "text"
            summary = f"{distinct} distinct"
        field_rows.append({"name": name, "type": ktype,
                           "missing": round(missing_pct, 1),
                           "distinct": distinct, "summary": summary})
    n_cells = n_rows * len(field_names)
    completeness = 100.0 * filled_cells / n_cells if n_cells else 100.0

    # ── categorical fields → top-N count bars (clickable) ──
    for name in cat_fields[:MAX_CAT_CHARTS]:
        cats, vals, ids = transform.group_rows(cols[name], [], fids, "count")
        cats, vals, ids = transform.sort_cats(cats, vals, ids, "value_desc")
        collapsed = len(cats) > MAX_CATS_SHOWN
        cats, vals, ids = transform.topn_collapse(cats, vals, ids, MAX_CATS_SHOWN)
        tiles.append({"span": 1, "source": ("count", name, cats, collapsed), "spec": spec(
            "bar", f"{name} — counts", x=name, y="count",
            data={"categories": cats,
                  "series": [{"name": "count", "values": vals, "ids": ids}]})})
        if cats and n_rows:
            share = 100.0 * vals[0] / n_rows
            insights.append(
                f"'{cats[0]}' is the largest {name} group "
                f"({int(vals[0])} of {n_rows} rows, {share:.0f}%)")

    # ── numeric fields → histograms ──
    for name in num_fields[:MAX_NUM_CHARTS]:
        labels, counts = stats.histogram(cols[name], HIST_BINS)
        if not labels:
            continue
        mean = num_stats[name]["mean"] if name in num_stats else 0.0
        tiles.append({"span": 1, "source": ("hist", name, stats.histogram_range(cols[name]),
                                            len(counts)), "spec": spec(
            "histogram", f"{name} — distribution (mean {_fmt(mean)})",
            x=name, y="count", data={"categories": labels, "values": counts})})

    # ── numeric fields on one comparable axis (min–max normalised box) ──
    if len(num_stats) >= 2:
        box_names, box_stats = [], []
        for name in list(num_stats)[:8]:
            st = stats.boxplot_stats(stats.minmax_normalize(cols[name]))
            if st is not None:
                box_names.append(name)
                box_stats.append(st)
        if len(box_names) >= 2:
            tiles.append({"span": 1, "spec": spec(
                "box", "Numeric fields — normalised spread (0–1, min–max)",
                y="normalised value",
                data={"groups": box_names, "stats": box_stats})})

    # ── correlations: matrix + strongest pair scatter ──
    best_pair, best_r = None, 0.0
    strong_pairs: list[tuple] = []
    if len(num_fields) >= 2:
        x_cats = num_fields[:8]
        cells = []
        for i, a in enumerate(x_cats):
            for j, b in enumerate(x_cats):
                r = 1.0 if i == j else stats.pearson(cols[a], cols[b])
                if r is None:
                    continue
                cells.append([i, j, round(r, 2)])
                if i < j:
                    if abs(r) > abs(best_r):
                        best_pair, best_r = (a, b), r
                    if abs(r) >= 0.4:
                        strong_pairs.append((abs(r), a, b, r))
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
            tiles.append({"span": 1, "source": ("scatter", a, b), "spec": spec(
                "scatter", f"{a} vs {b} (r = {best_r:.2f})", x=a, y=b,
                data={"series": [{"name": f"{a}/{b}", "points": points}],
                      "trend": transform.linreg_endpoints(points)})})
        verdict = ("strong" if abs(best_r) >= 0.7 else
                   "moderate" if abs(best_r) >= 0.4 else "weak")
        direction = "positive" if best_r > 0 else "negative"
        insights.insert(0, f"Strongest link: {a} ↔ {b} "
                           f"(r = {best_r:.2f}, {verdict} {direction})")
    # a couple more notable correlations, strongest first
    for _absr, a, b, r in sorted(strong_pairs, reverse=True)[1:3]:
        insights.append(f"{a} ↔ {b} correlate (r = {r:.2f})")

    # ── numeric shape: range, skew, outliers, near-constant ──
    if num_stats:
        widest = max(num_stats, key=lambda k: num_stats[k]["max"] - num_stats[k]["min"])
        st = num_stats[widest]
        insights.append(f"{widest} ranges {_fmt(st['min'])} – {_fmt(st['max'])} "
                        f"(mean {_fmt(st['mean'])})")
        skews = []
        for name in num_stats:
            sk = stats.skewness(cols[name])
            if sk is not None and abs(sk) >= 1.0:
                skews.append((abs(sk), name, sk))
        if skews:
            _a, name, sk = max(skews)
            side = "right" if sk > 0 else "left"
            insights.append(f"{name} is {side}-skewed (skew {sk:+.1f}) — "
                            f"consider a log transform")
        outs = [(stats.outlier_count(cols[name]), name) for name in num_stats]
        outs = [(c, name) for c, name in outs if c > 0]
        if outs:
            c, name = max(outs)
            insights.append(f"{name} has {c} outlier{'s' if c != 1 else ''} "
                            f"(beyond 1.5×IQR)")
        ginis = []
        for name in num_stats:
            g = stats.gini(cols[name])
            if g is not None and g >= 0.40:
                ginis.append((g, name))
        if ginis:
            g, name = max(ginis)
            insights.append(f"{name} is concentrated (Gini = {g:.2f}) — "
                            f"inspect with a Lorenz & Gini curve")
        flat = [name for name, s in num_stats.items() if s["std"] == 0]
        if flat:
            insights.append(f"{len(flat)} numeric field"
                            f"{'s are' if len(flat) != 1 else ' is'} constant "
                            f"({', '.join(flat[:3])})")

    if high_null:
        insights.append(f"{len(high_null)} field"
                        f"{'s are' if len(high_null) != 1 else ' is'} "
                        f">30% empty ({', '.join(high_null[:3])})")

    kpis = [("Rows", f"{n_rows:,}"),
            ("Fields", str(len(field_names))),
            ("Numeric", str(len(num_fields))),
            ("Categorical", str(len(cat_fields))),
            ("Complete", f"{completeness:.0f}%")]

    frames = None
    if animate_by and n_rows:
        frames = _animate(tiles, cols, fids, cols[animate_by], animate_by, interval)
        if frames is None:
            insights.append(f"Animate by {animate_by} needs at least two values: "
                            f"showing all rows")
        else:
            frames["kpis"] = _kpi_frames(cols, field_names, frames.pop("_idx"),
                                         len(num_fields), len(cat_fields))

    section_of = {"bar": "count_bars", "histogram": "histograms", "heatmap": "corr_matrix", "scatter": "scatter_trend", "box": "normalised_box"}
    tiles = [dict(tile, section=section_of.get(tile["spec"].get("type"), "count_bars"))
             for tile in tiles if section_of.get(tile["spec"].get("type"), "count_bars") in wanted]
    return {"title": layer.name(),
            "meta": f"{n_rows:,} rows · {len(field_names)} fields · "
                    f"{completeness:.0f}% complete"
                    + (" · selection only" if selected_only else "")
                    + (f" · limited: {extraction.status_note}"
                       if extraction.truncated else ""),
            "kpis": kpis if "kpis" in wanted else [], "insights": insights[:7] if "insights" in wanted else [], "tiles": tiles,
            "fields": field_rows if "fields" in wanted else [],
            "frames": frames}

def _animate(tiles, cols, fids, frame_col, field, interval):
    """Attach per-frame data to every animatable tile, on the whole-layer axis.
    → the profile's "frames" header, or None with fewer than two frames."""
    labels, idx_per = transform.frame_groups(frame_col)
    if len(labels) < 2:
        return None
    for tile in tiles:
        src = tile.get("source")
        if not src:
            continue
        datas, bounds = [], None
        if src[0] == "count":
            _kind, name, cats, collapsed = src
            named = cats[:-1] if collapsed else cats
            pos = {c: i for i, c in enumerate(named)}
            for idxs in idx_per:
                vals = [0.0] * len(cats)
                ids = [[] for _ in cats]
                for i in idxs:
                    j = pos.get(transform._key(cols[name][i]))
                    if j is None:
                        if not collapsed:
                            continue
                        j = len(cats) - 1
                    vals[j] += 1.0
                    ids[j].append(fids[i])
                datas.append({"categories": cats,
                              "series": [{"name": "count", "values": vals, "ids": ids}]})
            bounds = {"y": [0.0, max(max(d["series"][0]["values"]) for d in datas)]}
        elif src[0] == "hist":
            _kind, name, rng, bins = src
            if rng is None:
                continue
            cats = tile["spec"]["data"]["categories"]
            for idxs in idx_per:
                counts = stats.bin_counts([cols[name][i] for i in idxs], rng[0], rng[1], bins)
                datas.append({"categories": cats, "values": counts})
            bounds = {"y": [0.0, max(max(d["values"]) for d in datas)]}
        elif src[0] == "scatter":
            _kind, a, b = src
            series_name = tile["spec"]["data"]["series"][0]["name"]
            xs, ys = [], []
            for idxs in idx_per:
                pts = []
                for i in idxs[:MAX_SCATTER_POINTS]:
                    xf, yf = stats.to_float(cols[a][i]), stats.to_float(cols[b][i])
                    if xf is not None and yf is not None:
                        pts.append([xf, yf, None, fids[i]])
                        xs.append(xf)
                        ys.append(yf)
                datas.append({"series": [{"name": series_name, "points": pts}], "trend": None})
            if xs:
                bounds = {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)]}
        if datas:
            tile["frames"] = {"datas": datas, "bounds": bounds}
    return {"field": field, "labels": labels, "interval": int(interval), "_idx": idx_per}


def _kpi_frames(cols, field_names, idx_per, n_numeric, n_categorical):
    """KPI values per frame, in the same order as the static KPI cards.
    A frame with no rows shows "–" for its row-derived KPIs, never a stale
    number carried over from the previous frame."""
    out = []
    for idxs in idx_per:
        n = len(idxs)
        if n and field_names:
            filled = sum(1 for name in field_names for i in idxs if cols[name][i] is not None)
            complete = f"{100.0 * filled / (n * len(field_names)):.0f}%"
            rows = f"{n:,}"
        elif n:
            complete, rows = "100%", f"{n:,}"
        else:
            complete = rows = "–"
        out.append([rows, str(len(field_names)), str(n_numeric), str(n_categorical), complete])
    return out

