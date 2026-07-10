# -*- coding: utf-8 -*-
"""Data shaping for charts: grouping, pivoting, top-N, sorting, trend.

Everything here is pure Python and carries *feature ids* alongside the
shaped values, so charts stay clickable: a bar/slice/point knows which
features it represents and can select them back on the map canvas.
"""
from __future__ import annotations

import math

from .stats import _median, kde_points, mean_std, to_float

SORT_MODES = ("natural", "value_desc", "value_asc")


def _key(value) -> str:
    return "(null)" if value is None else str(value)


def _reduce(vals: list[float], count: int, how: str) -> float:
    if how == "count":
        return float(count)
    if not vals:
        return 0.0
    if how == "sum":
        return sum(vals)
    if how == "mean":
        return sum(vals) / len(vals)
    if how == "median":
        return _median(sorted(vals))
    if how == "min":
        return min(vals)
    if how == "max":
        return max(vals)
    raise ValueError(f"Unsupported aggregation: {how}")


def group_rows(xs: list, ys: list, fids: list, how: str):
    """Single-series grouping → (categories, values, ids_per_category)."""
    order: list[str] = []
    nums: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    ids: dict[str, list] = {}
    for i, x in enumerate(xs):
        k = _key(x)
        if k not in counts:
            order.append(k)
            counts[k] = 0
            nums[k] = []
            ids[k] = []
        counts[k] += 1
        ids[k].append(fids[i] if i < len(fids) else None)
        if how != "count" and i < len(ys):
            f = to_float(ys[i])
            if f is not None:
                nums[k].append(f)
    values = [_reduce(nums[k], counts[k], how) for k in order]
    return order, values, [ids[k] for k in order]


def pivot_rows(xs: list, series: list, ys: list, fids: list, how: str):
    """Two-way pivot → (categories, [{name, values, ids}]) for grouped /
    stacked bars, multi-line and multi-area charts."""
    cat_order: list[str] = []
    ser_order: list[str] = []
    nums: dict[tuple, list[float]] = {}
    counts: dict[tuple, int] = {}
    ids: dict[tuple, list] = {}
    for i, x in enumerate(xs):
        cx, cs = _key(x), _key(series[i] if i < len(series) else None)
        if cx not in cat_order:
            cat_order.append(cx)
        if cs not in ser_order:
            ser_order.append(cs)
        cell = (cs, cx)
        if cell not in counts:
            counts[cell] = 0
            nums[cell] = []
            ids[cell] = []
        counts[cell] += 1
        ids[cell].append(fids[i] if i < len(fids) else None)
        if how != "count" and i < len(ys):
            f = to_float(ys[i])
            if f is not None:
                nums[cell].append(f)
    out = []
    for cs in ser_order:
        values, id_rows = [], []
        for cx in cat_order:
            cell = (cs, cx)
            if cell in counts:
                values.append(_reduce(nums[cell], counts[cell], how))
                id_rows.append(ids[cell])
            else:
                values.append(0.0)
                id_rows.append([])
        out.append({"name": cs, "values": values, "ids": id_rows})
    return cat_order, out


def heatmap_rows(xs: list, ys: list, vals: list, how: str):
    """→ (x_cats, y_cats, cells [[xi, yi, value]], vmin, vmax)."""
    x_cats, y_cats = [], []
    nums: dict[tuple, list[float]] = {}
    counts: dict[tuple, int] = {}
    for i, x in enumerate(xs):
        cx, cy = _key(x), _key(ys[i] if i < len(ys) else None)
        if cx not in x_cats:
            x_cats.append(cx)
        if cy not in y_cats:
            y_cats.append(cy)
        cell = (cx, cy)
        if cell not in counts:
            counts[cell] = 0
            nums[cell] = []
        counts[cell] += 1
        if how != "count" and i < len(vals):
            f = to_float(vals[i])
            if f is not None:
                nums[cell].append(f)
    cells, flat = [], []
    for (cx, cy), n in counts.items():
        v = _reduce(nums[(cx, cy)], n, how)
        cells.append([x_cats.index(cx), y_cats.index(cy), v])
        flat.append(v)
    return x_cats, y_cats, cells, (min(flat) if flat else 0), (max(flat) if flat else 0)


def tree_rows(groups: list, subs: list, vals: list, how: str, fids: list | None = None) -> list[dict]:
    """→ nested nodes [{name, value, children:[{name, value}]}] for
    treemap / sunburst. ``subs`` may be empty (flat hierarchy)."""
    g_order: list[str] = []
    children: dict[str, dict] = {}
    for i, g in enumerate(groups):
        cg = _key(g)
        cs = _key(subs[i]) if i < len(subs) and subs else None
        if cg not in children:
            g_order.append(cg)
            children[cg] = {}
        bucket = children[cg].setdefault(cs, {"nums": [], "count": 0, "ids": []})
        bucket["count"] += 1
        if how != "count" and i < len(vals):
            f = to_float(vals[i])
            if f is not None:
                bucket["nums"].append(f)
    nodes = []
    for cg in g_order:
        kids = []
        for cs, bucket in children[cg].items():
            value = _reduce(bucket["nums"], bucket["count"], how)
            if cs is None:
                kids.append({"name": cg, "value": value, "__ids": list(bucket["ids"])})
            else:
                kids.append({"name": cs, "value": value, "__ids": list(bucket["ids"])})
        total = sum(k["value"] for k in kids)
        node = {"name": cg, "value": total, "__ids": [fid for kid in kids for fid in kid.get("__ids", [])]}
        if not (len(kids) == 1 and kids[0]["name"] == cg):
            node["children"] = kids
        nodes.append(node)
    return nodes


def topn_collapse(cats: list[str], vals: list[float], ids: list[list] | None, n: int,
                  others_label: str = "Other"):
    """Keep the n largest categories, collapse the rest into one bucket."""
    if n <= 0 or len(cats) <= n:
        return cats, vals, ids
    ranked = sorted(range(len(cats)), key=lambda i: vals[i], reverse=True)
    keep = sorted(ranked[:n])  # preserve original order among the kept
    rest = ranked[n:]
    out_c = [cats[i] for i in keep] + [others_label]
    out_v = [vals[i] for i in keep] + [sum(vals[i] for i in rest)]
    out_i = None
    if ids is not None:
        merged: list = []
        for i in rest:
            merged.extend(ids[i])
        out_i = [ids[i] for i in keep] + [merged]
    return out_c, out_v, out_i


def sort_cats(cats: list[str], vals: list[float], ids: list[list] | None, mode: str):
    if mode not in SORT_MODES:
        raise ValueError(f"Unsupported sort mode: {mode}")
    if mode == "natural" or not cats:
        return cats, vals, ids
    order = sorted(range(len(cats)), key=lambda i: vals[i],
                   reverse=(mode == "value_desc"))
    return ([cats[i] for i in order], [vals[i] for i in order],
            [ids[i] for i in order] if ids is not None else None)


def band_rows(xs: list, ys: list, groups: list | None, fids: list, k: float = 1.0):
    """Mean ± k·std per category (optionally per group) for error band/bar
    charts → (categories, [{name, mean, lo, hi, ids}])."""
    cat_order: list[str] = []
    ser_order: list[str] = []
    nums: dict[tuple, list[float]] = {}
    ids: dict[tuple, list] = {}
    for i, x in enumerate(xs):
        cx = _key(x)
        cs = _key(groups[i]) if groups and i < len(groups) else ""
        if cx not in cat_order:
            cat_order.append(cx)
        if cs not in ser_order:
            ser_order.append(cs)
        cell = (cs, cx)
        if cell not in nums:
            nums[cell] = []
            ids[cell] = []
        ids[cell].append(fids[i] if i < len(fids) else None)
        f = to_float(ys[i]) if i < len(ys) else None
        if f is not None:
            nums[cell].append(f)
    out = []
    for cs in ser_order:
        means, los, his, id_rows = [], [], [], []
        for cx in cat_order:
            ms = mean_std(nums.get((cs, cx), []))
            if ms is None:
                means.append(None)
                los.append(None)
                his.append(None)
            else:
                means.append(ms[0])
                los.append(ms[0] - k * ms[1])
                his.append(ms[0] + k * ms[1])
            id_rows.append(ids.get((cs, cx), []))
        if any(m is not None for m in means):
            out.append({"name": cs, "mean": means, "lo": los, "hi": his,
                        "ids": id_rows})
    return (cat_order, out) if out else ([], [])


def violin_rows(order: list[str], buckets: dict[str, list], points: int = 60,
                half_width: float = 0.42):
    """KDE violin shapes on a numeric axis: group i sits at x = i and its
    density is mirrored into a closed polygon of at most ``half_width``
    → (groups, polygons, medians). Groups too small for a KDE are dropped."""
    groups, polygons, medians = [], [], []
    for key in order:
        kde = kde_points(buckets[key], points)
        if not kde:
            continue
        peak = max(d for _, d in kde) or 1.0
        i = len(groups)
        left = [[i - half_width * d / peak, y] for y, d in kde]
        right = [[i + half_width * d / peak, y] for y, d in kde]
        polygons.append(left + right[::-1])
        nums = sorted(v for v in (to_float(x) for x in buckets[key]) if v is not None)
        groups.append(key)
        medians.append(_median(nums))
    return groups, polygons, medians


def pareto_rows(cats: list[str], vals: list[float], ids: list[list] | None):
    """Sort descending and add the cumulative share (0–100 %)
    → (categories, values, cum, ids)."""
    order = sorted(range(len(cats)), key=lambda i: vals[i], reverse=True)
    cats = [cats[i] for i in order]
    vals = [vals[i] for i in order]
    ids = [ids[i] for i in order] if ids is not None else None
    total = sum(vals) or 1.0
    cum, running = [], 0.0
    for v in vals:
        running += v
        cum.append(round(100.0 * running / total, 2))
    return cats, vals, cum, ids


def radar_axis_maxes(series: list[dict], pad: float = 1.05) -> list[float]:
    """Per-axis maxima (padded) so every engine scales radar axes alike."""
    if not series:
        return []
    n = max(len(s.get("values", [])) for s in series)
    maxes = []
    for i in range(n):
        vals = [s["values"][i] for s in series
                if i < len(s.get("values", [])) and s["values"][i] is not None]
        peak = max((abs(v) for v in vals), default=1.0) or 1.0
        maxes.append(peak * pad)
    return maxes


def linreg_endpoints(points: list) -> list | None:
    """Least-squares trend line → [[x0, y0], [x1, y1]] or None."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / sxx
    intercept = my - slope * mx
    x0, x1 = min(xs), max(xs)
    return [[x0, slope * x0 + intercept], [x1, slope * x1 + intercept]]


def bubble_sizes(values: list, lo: float = 6.0, hi: float = 38.0) -> list[float]:
    """Map raw values to pixel sizes (sqrt scale, perceptually honest)."""
    nums = [to_float(v) for v in values]
    finite = [v for v in nums if v is not None]
    if not finite:
        return [lo] * len(values)
    vmin, vmax = min(finite), max(finite)
    if vmax == vmin:
        return [(lo + hi) / 2] * len(values)
    out = []
    for v in nums:
        if v is None:
            out.append(lo)
        else:
            out.append(lo + (hi - lo) * math.sqrt((v - vmin) / (vmax - vmin)))
    return out


# ─────────────────────────── animation (play axis) ───────────────────────────
#
# A "play axis" turns a single field (typically a year or sequence) into the
# frames of an animation. Everything here is pure Python: the dock slices a
# layer's rows per frame, runs the ordinary per-type builders on each slice,
# then uses these helpers to give every frame a *stable* axis — the same
# category order and the same colour per series — so categories animate in
# place (bar-chart race, Gapminder bubbles) instead of jumping around.


def frame_groups(frame_col: list):
    """Partition row indices by their value in ``frame_col`` and order the
    distinct frames like a time axis: numerically when every frame value is a
    number (so 2000, 2001, … 2010 — not 2000, 2001, 2010, 2002 …), otherwise
    lexicographically. → ``(frame_labels, [row_indices_per_frame])``."""
    order: list[str] = []
    buckets: dict[str, list[int]] = {}
    for i, v in enumerate(frame_col):
        k = _key(v)
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(i)
    nums = [to_float(k) for k in order]
    if order and all(n is not None for n in nums):
        order = [k for _, k in sorted(zip(nums, order), key=lambda p: p[0])]
    else:
        order = sorted(order)
    return order, [buckets[k] for k in order]


def union_categories(cat_lists: list) -> list[str]:
    """Merge the category lists of every frame into one stable, deterministic
    axis (numeric-aware), so each category keeps its slot — and therefore its
    colour and position — for the whole animation."""
    seen: set = set()
    merged: list[str] = []
    for lst in cat_lists:
        for c in lst:
            if c not in seen:
                seen.add(c)
                merged.append(c)
    nums = [to_float(c) for c in merged]
    if merged and all(n is not None for n in nums):
        return [c for _, c in sorted(zip(nums, merged), key=lambda p: p[0])]
    return sorted(merged)


def align_values(target: list, cats: list, values: list, ids: list | None = None):
    """Re-index one frame's ``(cats → values[, ids])`` onto the ``target``
    category order; a category missing from this frame becomes 0 (empty id
    list). → ``(values, ids_or_None)`` both aligned to ``target``."""
    pos = {c: i for i, c in enumerate(cats)}
    out_v = [0.0] * len(target)
    out_i = [[] for _ in target] if ids is not None else None
    for j, c in enumerate(target):
        i = pos.get(c)
        if i is not None:
            out_v[j] = values[i] if i < len(values) else 0.0
            if out_i is not None and i < len(ids):
                out_i[j] = ids[i]
    return out_v, out_i


def build_frames(kind: str, cols: dict, fids: list, frame_col: list, *,
                 x: str, y: str, group: str, value: str, how: str,
                 single_name: str = "points"):
    """Pure animation builder: slice the row-aligned ``cols`` by ``frame_col``
    and rebuild ``kind`` for every frame, with a stable category/series order
    (union) and a global value range.

    → ``(labels, datas, union_categories_or_None, bounds_or_None)`` where each
    ``datas[i]`` is a per-frame ``spec["data"]`` dict, or ``None`` when there
    are fewer than two frames / no chartable data to animate."""
    labels, idx_per = frame_groups(frame_col)
    if len(labels) < 2:
        return None

    def sub(name, idxs):
        col = cols.get(name, [])
        return [col[i] for i in idxs]

    datas: list[dict] = []
    union = None
    bounds = None

    if kind in ("bar", "line", "area", "pie"):
        use_group = bool(group) and kind != "pie"
        raw = []
        for idxs in idx_per:
            ff = [fids[i] for i in idxs]
            if use_group:
                cats, series = pivot_rows(sub(x, idxs), sub(group, idxs),
                                          sub(y, idxs), ff, how)
            else:
                cats, vals, ids = group_rows(sub(x, idxs), sub(y, idxs), ff, how)
                series = [{"name": single_name, "values": vals, "ids": ids}]
            raw.append((cats, series))
        union = union_categories([c for c, _s in raw])
        names: list[str] = []
        for _c, series in raw:
            for s in series:
                if s["name"] not in names:
                    names.append(s["name"])
        all_vals: list[float] = []
        for cats, series in raw:
            by_name = {s["name"]: s for s in series}
            aligned = []
            for nm in names:
                s = by_name.get(nm)
                if s is None:
                    aligned.append({"name": nm, "values": [0.0] * len(union),
                                    "ids": [[] for _ in union]})
                else:
                    vv, ii = align_values(union, cats, s["values"], s.get("ids"))
                    aligned.append({"name": nm, "values": vv, "ids": ii})
            all_vals.extend(v for s in aligned for v in s["values"])
            if kind == "pie":
                datas.append({"categories": union, "values": aligned[0]["values"],
                              "ids": aligned[0]["ids"]})
            else:
                datas.append({"categories": union, "series": aligned})
        if all_vals:
            bounds = {"y": [min(all_vals + [0.0]), max(all_vals + [0.0])]}

    elif kind in ("scatter", "bubble"):
        # bubble radii are scaled once, globally, so a value maps to the same
        # size in every frame
        sizes = (bubble_sizes(cols[value])
                 if (kind == "bubble" and value) else [None] * len(fids))
        names = []
        for i in range(len(fids)):
            key = _key(cols[group][i]) if group else single_name
            if key not in names:
                names.append(key)
        xs_all: list[float] = []
        ys_all: list[float] = []
        for idxs in idx_per:
            buckets: dict[str, list] = {nm: [] for nm in names}
            for i in idxs:
                xf = to_float(cols[x][i])
                yf = to_float(cols[y][i])
                if xf is None or yf is None:
                    continue
                key = _key(cols[group][i]) if group else single_name
                buckets[key].append([xf, yf, sizes[i], fids[i]])
                xs_all.append(xf)
                ys_all.append(yf)
            datas.append({"series": [{"name": nm, "points": buckets[nm]}
                                     for nm in names], "trend": None})
        if not xs_all:
            return None
        bounds = {"x": [min(xs_all), max(xs_all)],
                  "y": [min(ys_all), max(ys_all)]}
    else:
        return None

    return labels, datas, union, bounds
