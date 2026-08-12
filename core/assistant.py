# -*- coding: utf-8 -*-
"""Offline smart assistant — pure, no ``qgis`` import, no network.

Looks at the *actual* fields of the active layer and recommends concrete,
ready-to-run visualizations across the three surfaces (charts, map diagrams,
labels). No model, no API key, no internet: just the same field semantics and
statistics the rest of 02viz uses, turned into plain-English advice. The dock
can apply :func:`suggest_chart` to its controls with one click and lists
:func:`suggestions` in a panel; the guide embeds them for the current layer.
"""
from __future__ import annotations

from . import expressions, fields, stats, transform

# The "most correlated pair" scan below is O(fields^2 * rows): a plain
# vector/CSV layer has a handful of numeric fields, but a grid / zonal-stats
# layer routinely carries dozens to hundreds of derived numeric columns over
# up to datasource.MAX_ROWS (100k) rows — uncapped, that is easily hundreds
# of millions of pure-Python operations run synchronously on the UI thread,
# which reads to the user as QGIS freezing or being killed outright rather
# than a slow Suggest. Bound both dimensions: only the first
# _CORR_FIELD_CAP numeric fields enter the pairwise scan, and each pair's
# correlation is computed over an evenly-spaced sample of at most
# _CORR_SAMPLE_CAP rows — plenty to find a strong linear relationship,
# nowhere near enough to hang the app.
_CORR_FIELD_CAP = 40
_CORR_SAMPLE_CAP = 5000
# classify() also scans every value of every field just to tell numeric from
# categorical from noise — same F*N cost, same fix: a sample is enough to
# call the type with high confidence.
_CLASSIFY_SAMPLE_CAP = 10_000


def _sample_indices(n: int, cap: int) -> list[int]:
    if n <= cap:
        return list(range(n))
    step = n / cap
    return [int(i * step) for i in range(cap)]


def _sample(values: list, cap: int) -> list:
    if len(values) <= cap:
        return values
    return [values[i] for i in _sample_indices(len(values), cap)]


def _kinds(cols: dict) -> dict:
    return {name: ("id" if fields.is_id_name(name)
                   else fields.classify(_sample(values, _CLASSIFY_SAMPLE_CAP)))
            for name, values in cols.items()}


def _best_categorical(cols: dict, kinds: dict) -> str | None:
    """A categorical field worth grouping by: the most informative one whose
    cardinality is neither 1 nor huge."""
    best, best_d = None, 0
    for name, k in kinds.items():
        if k != "categorical":
            continue
        d = len({str(v) for v in cols[name] if v is not None})
        if 1 < d <= 20 and d > best_d:
            best, best_d = name, d
    return best


def _label_candidate(cols: dict, kinds: dict) -> str | None:
    """A name/title-like field for labelling: a high-cardinality text field
    (names usually read as 'skip' because they are nearly unique)."""
    named = ("name", "title", "label", "ad", "isim", "ada", "mahalle",
             "district", "city", "il", "ilce", "street", "sokak")
    text_fields = []
    for name, k in kinds.items():
        if k == "id":
            continue
        non_null = [v for v in cols[name] if v is not None]
        if not non_null:
            continue
        numeric = sum(1 for v in (stats.to_float(x) for x in non_null) if v is not None)
        if numeric >= 0.6 * len(non_null):
            continue  # mostly numeric → not a label
        d = len({str(v) for v in non_null})
        bonus = 1000 if name.lower() in named else 0
        text_fields.append((bonus + d, name))
    if not text_fields:
        return None
    return max(text_fields)[1]


def would_sample(numeric_field_count: int, row_count: int) -> bool:
    """True if a correlation scan over this many numeric fields/rows would
    exceed the default caps — usable from field/row counts alone (e.g. the
    dock's own cheap layer metadata, before pulling any data), not just an
    already-pulled ``cols`` dict. See :func:`scan_would_sample`."""
    return numeric_field_count > _CORR_FIELD_CAP or row_count > _CORR_SAMPLE_CAP


def scan_would_sample(cols: dict) -> bool:
    """True if :func:`suggest_chart`'s default (``full=False``) correlation
    scan would use fewer fields/rows than the layer actually has — lets the
    dock warn and offer a full-dataset re-scan before it happens, rather
    than silently narrowing the search."""
    kinds = _kinds(cols)
    num = [n for n, k in kinds.items() if k == "numeric"]
    if len(num) < 2:
        return False
    rows = len(cols[num[0]]) if num else 0
    return would_sample(len(num), rows)


def suggest_chart(cols: dict, fids: list | None = None, *, full: bool = False) -> dict | None:
    """The single most insightful chart for these fields, as a config the dock
    can drop straight into its controls.

    → ``{type, x, y, group, value, agg, title, why, sampled}`` or ``None``.
    ``sampled`` is True when the correlation search (see module docstring)
    used a bounded subset of fields/rows rather than the whole layer; pass
    ``full=True`` to scan everything regardless of size (the dock only does
    this after the user explicitly confirms — see :func:`scan_would_sample`).
    """
    kinds = _kinds(cols)
    num = [n for n, k in kinds.items() if k == "numeric"]
    cat = [n for n, k in kinds.items() if k == "categorical"]

    # Whether the correlation scan below (if it runs) will be limited to a
    # subset of fields/rows — tracked once so EVERY branch's return value
    # (not just a winning scatter) can honestly say a fuller search was
    # possible, even when the capped scan finds nothing above threshold and
    # the assistant falls back to a category/histogram suggestion instead.
    was_sampled = (not full) and scan_would_sample(cols)

    # 1) two numerics that move together → scatter with a trend line
    if len(num) >= 2:
        if full:
            scan = num
            sampled_cols = {name: cols[name] for name in scan}
        else:
            scan = num[:_CORR_FIELD_CAP]
            sampled_cols = {name: _sample(cols[name], _CORR_SAMPLE_CAP) for name in scan}
        best, best_r = None, 0.0
        for i in range(len(scan)):
            for j in range(i + 1, len(scan)):
                r = stats.pearson(sampled_cols[scan[i]], sampled_cols[scan[j]])
                if r is not None and abs(r) > abs(best_r):
                    best, best_r = (scan[i], scan[j]), r
        if best and abs(best_r) >= 0.4:
            a, b = best
            return {"type": "scatter", "x": a, "y": b, "group": "", "value": "",
                    "agg": "none", "trend": True, "sampled": was_sampled,
                    "title": f"{a} vs {b}",
                    "why": f"{a} and {b} are the most correlated pair "
                           f"(r = {best_r:.2f}) — a scatter with a trend line "
                           f"shows the relationship."}

    # 2) a category + a measure → mean bar chart
    gcat = _best_categorical(cols, kinds)
    if gcat and num:
        y = num[0]
        return {"type": "bar", "x": gcat, "y": y, "group": "", "value": "",
                "agg": "mean", "trend": False, "sampled": was_sampled,
                "title": f"mean {y} by {gcat}",
                "why": f"Comparing the average {y} across {gcat} groups is a "
                       f"clear first read of the data."}

    # 3) just a category → count bar chart
    if gcat:
        return {"type": "bar", "x": gcat, "y": "", "group": "", "value": "",
                "agg": "count", "trend": False, "sampled": was_sampled,
                "title": f"{gcat} counts",
                "why": f"{gcat} is your most informative category — count its "
                       f"values to see the distribution."}

    # 4) just a number → histogram
    if num:
        x = num[0]
        return {"type": "histogram", "x": x, "y": "", "group": "", "value": "",
                "agg": "none", "trend": False, "sampled": was_sampled,
                "title": f"{x} distribution",
                "why": f"A histogram reveals the shape and spread of {x}."}
    return None


def _scale_disparity(cols: dict, num: list) -> tuple:
    """(ratio, small_field, big_field) of the largest vs smallest field
    magnitude among ``num``; ratio 0 when not comparable."""
    mags = []
    for name in num:
        st = stats.field_numeric_stats(cols[name])
        if st:
            mag = max(abs(st["min"]), abs(st["max"]), abs(st["mean"]))
            if mag > 0:
                mags.append((mag, name))
    if len(mags) < 2:
        return 0.0, None, None
    mags.sort()
    lo, hi = mags[0], mags[-1]
    return hi[0] / lo[0], lo[1], hi[1]


def suggestions(cols: dict, *, has_geometry: bool = True,
                fids: list | None = None) -> list[dict]:
    """Ranked, human-readable recommendations across all three surfaces.

    → ``[{surface, title, why, how}]`` where ``surface`` ∈
    ``chart | diagram | label | explore``.
    """
    kinds = _kinds(cols)
    num = [n for n, k in kinds.items() if k == "numeric"]
    out: list[dict] = []

    chart = suggest_chart(cols, fids)
    if chart:
        out.append({"surface": "chart", "title": chart["title"],
                    "why": chart["why"],
                    "how": "Charts tab → 💡 Suggest applies this in one click, "
                           "or set Type / X / Y / Aggregate to match."})

    # map diagrams: normalise when numeric fields differ wildly in scale
    if has_geometry and len(num) >= 2:
        ratio, small, big = _scale_disparity(cols, num)
        if ratio >= 50 and small and big:
            out.append({
                "surface": "diagram",
                "title": f"Map diagram of {big} & {small} — normalised",
                "why": f"{big} is ~{ratio:,.0f}× the scale of {small}; raw pie "
                       f"slices or bars would be unreadable. Min–max (0–1) makes "
                       f"them comparable on every feature.",
                "how": "Diagrams tab → tick the fields → Normalize = "
                       "Min–max (0–1) → Apply to layer."})
        elif num:
            out.append({
                "surface": "diagram",
                "title": f"Map diagram comparing {', '.join(num[:3])}",
                "why": "Draw a small chart on every feature to compare these "
                       "measures in place on the map.",
                "how": "Diagrams tab → tick fields → Apply (use Z-score or "
                       "Log if the scales differ)."})

    # labels: a name + an optional rounded value on a second line
    lab = _label_candidate(cols, kinds)
    if lab:
        if num:
            expr = expressions.label_expression([lab, num[0]], decimals=1,
                                                 numeric_fields={num[0]})
            out.append({
                "surface": "label",
                "title": f"Label by {lab} with {num[0]} underneath",
                "why": f"Show each feature's {lab} and a rounded {num[0]} on a "
                       f"second line — readable, publication-style labels.",
                "how": f"Labels tab → Label field = {lab}, Second line = "
                       f"{num[0]}, Decimals = 1.  Expression: {expr}"})
        else:
            out.append({
                "surface": "label",
                "title": f"Label features by {lab}",
                "why": f"{lab} reads as the natural name for each feature.",
                "how": f"Labels tab → Label field = {lab} → Apply."})

    out.append({
        "surface": "explore",
        "title": "Explore the whole layer at once",
        "why": "One click profiles every field into a dashboard — KPIs, a field "
               "table, distributions, a correlation matrix and plain-English "
               "insights.",
        "how": "Charts tab → ✨ Explore layer."})
    return out
