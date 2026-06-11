# -*- coding: utf-8 -*-
"""Engine contract.

A chart engine turns a *spec* dict into a fully self-contained HTML
document (vendored JS inlined — charts must render offline).

Spec contract (produced by the dock, consumed by every engine):

    {
        "type":   "bar" | "line" | "scatter" | "histogram" | "pie" | "box",
        "title":  str,
        "x_label": str,
        "y_label": str,
        "data": {
            # bar / line / histogram / pie:
            "categories": [str, ...], "values": [float, ...],
            # scatter:
            "points": [[x, y], ...],
            # box:
            "groups": [str, ...], "stats": [[min, q1, med, q3, max], ...],
        },
    }
"""
from __future__ import annotations

CHART_TYPES = ("bar", "line", "scatter", "histogram", "pie", "box")


class ChartEngine:
    id = "base"
    label = "Base"

    def build_html(self, spec: dict) -> str:
        raise NotImplementedError
