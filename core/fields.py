# -*- coding: utf-8 -*-
"""Field semantics — pure, no ``qgis`` import.

Deciding whether a column is *numeric*, *categorical* or analytical *noise*
(identifier-like) is needed in two places: the Explore profiler and the smart
assistant. Keeping the rules here means one source of truth and headless
tests.
"""
from __future__ import annotations

import re

from . import stats

# Identifier-like field names carry no analytical meaning — a histogram of
# gid 1..N or a bar of unique uuids is pure noise. Skip them.
_ID_NAME_RE = re.compile(
    r"^(f?id|gid|oid|ogc_fid|object_?id|row_?id|pk\w*|uu?id|guid|"
    r"globalid|index)$|(_id|_fid|_oid|_uid|_uuid|_guid|_key|_pk)$",
    re.IGNORECASE,
)


def is_id_name(name: str) -> bool:
    """True for fid / id / gid / uuid / objectid / *_id … style fields."""
    return bool(_ID_NAME_RE.search((name or "").strip()))


def classify(values: list) -> str:
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
