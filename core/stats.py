# -*- coding: utf-8 -*-
"""Pure-Python statistics helpers (no numpy/pandas — Hub-safe, testable headless)."""
from __future__ import annotations

import math

AGGREGATIONS = ("none", "count", "sum", "mean", "median", "min", "max")


def to_float(value):
    """Best-effort numeric coercion; returns None for anything non-finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _median(sorted_vals: list[float]) -> float:
    n = len(sorted_vals)
    mid = n // 2
    if n % 2:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def aggregate(xs: list, ys: list, how: str) -> tuple[list[str], list[float]]:
    """Group ys by xs (first-appearance order) and reduce each group.

    ``how='count'`` ignores ys entirely. Rows whose y is not numeric are
    skipped for numeric reductions.
    """
    if how not in AGGREGATIONS or how == "none":
        raise ValueError(f"Unsupported aggregation: {how}")

    groups: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    order: list[str] = []
    for i, x in enumerate(xs):
        key = "(null)" if x is None else str(x)
        if key not in counts:
            counts[key] = 0
            groups[key] = []
            order.append(key)
        counts[key] += 1
        if how != "count" and i < len(ys):
            f = to_float(ys[i])
            if f is not None:
                groups[key].append(f)

    values: list[float] = []
    for key in order:
        if how == "count":
            values.append(float(counts[key]))
            continue
        vals = groups[key]
        if not vals:
            values.append(0.0)
        elif how == "sum":
            values.append(sum(vals))
        elif how == "mean":
            values.append(sum(vals) / len(vals))
        elif how == "median":
            values.append(_median(sorted(vals)))
        elif how == "min":
            values.append(min(vals))
        elif how == "max":
            values.append(max(vals))
    return order, values


def histogram(values: list, bins: int = 20) -> tuple[list[str], list[int]]:
    """Equal-width binning. Returns (labels, counts); empty input → ([], [])."""
    nums = sorted(v for v in (to_float(x) for x in values) if v is not None)
    if not nums:
        return [], []
    lo, hi = nums[0], nums[-1]
    if lo == hi:
        return [f"{lo:g}"], [len(nums)]
    bins = max(1, int(bins))
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in nums:
        i = min(int((v - lo) / width), bins - 1)
        counts[i] += 1
    labels = [f"{lo + i * width:g}–{lo + (i + 1) * width:g}" for i in range(bins)]
    return labels, counts


def pearson(xs: list, ys: list) -> float | None:
    """Pearson correlation of the numeric pairs in xs/ys; None if degenerate."""
    pairs = [(a, b) for a, b in ((to_float(x), to_float(y)) for x, y in zip(xs, ys))
             if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    syy = sum((p[1] - my) ** 2 for p in pairs)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    return sxy / math.sqrt(sxx * syy)


def boxplot_stats(values: list) -> list[float] | None:
    """[min, Q1, median, Q3, max] with linear-interpolation quartiles."""
    nums = sorted(v for v in (to_float(x) for x in values) if v is not None)
    if not nums:
        return None

    def quantile(q: float) -> float:
        pos = q * (len(nums) - 1)
        lo_i = int(math.floor(pos))
        hi_i = min(lo_i + 1, len(nums) - 1)
        frac = pos - lo_i
        return nums[lo_i] * (1 - frac) + nums[hi_i] * frac

    return [nums[0], quantile(0.25), _median(nums), quantile(0.75), nums[-1]]
