# -*- coding: utf-8 -*-
"""Quick, elegant feature labels — QGIS native ``QgsPalLayerSettings``.

The third on-canvas surface (alongside charts and map diagrams): one click
turns a field into well-placed, publication-grade labels with a sensible
preset (subtle halo by default), no trip through the full labeling panel.
Pure QGIS API, headless-testable: ``apply_labels`` only sets the layer's
labeling, which ``layer.labelsEnabled()`` reflects without a canvas.
"""
from __future__ import annotations

from contextlib import suppress

from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    QgsPalLayerSettings,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)

# preset key → (label, halo-mm, bold) — the curated "elegant by default" set
PRESETS = (
    ("clean", "Clean (subtle halo)"),
    ("halo", "Strong halo"),
    ("bold", "Bold"),
    ("plain", "Plain"),
)
PRESET_LABELS = dict(PRESETS)
_HALO = {"clean": 0.6, "halo": 1.2, "bold": 0.6, "plain": 0.0}


def label_field_names(layer) -> list[str]:
    return [f.name() for f in layer.fields()]


def _placement_for(layer):
    """Geometry-appropriate label placement, scoped-enum safe (Qt5/Qt6)."""
    P = QgsPalLayerSettings
    try:
        around, over, curved = P.AroundPoint, P.OverPoint, P.Curved
    except AttributeError:  # QGIS 4 scoped enums
        around = P.Placement.AroundPoint
        over = P.Placement.OverPoint
        curved = P.Placement.Curved
    gtype = layer.geometryType()
    if gtype == QgsWkbTypes.PointGeometry:
        return around
    if gtype == QgsWkbTypes.LineGeometry:
        return curved
    return over  # polygons: centroid


def apply_labels(layer, *, field: str = "", expression: str = "",
                 preset: str = "clean", color: str = "#16323f",
                 size: float = 9.0, halo_color: str = "#ffffff") -> bool:
    """Label ``layer`` with a preset text style. Returns success.

    Pass ``expression`` (a QGIS expression — ``round("pop", 1)``,
    ``concat(name, char(10), …)``, ``wordwrap(…)`` …) to label by a formatted /
    multi-line value, or ``field`` to label by a single field verbatim. When
    both are given the expression wins. See :func:`core.expressions.label_expression`.
    """
    expr = (expression or "").strip()
    use_expr = bool(expr)
    if not use_expr and (not field or field not in label_field_names(layer)):
        return False

    fmt = QgsTextFormat()
    font = QFont("Segoe UI")
    if preset == "bold":
        font.setBold(True)
    fmt.setFont(font)
    fmt.setSize(float(size))
    fmt.setColor(QColor(color))

    halo = _HALO.get(preset, 0.6)
    if halo > 0:
        buf = QgsTextBufferSettings()
        buf.setEnabled(True)
        buf.setSize(halo)
        buf.setColor(QColor(halo_color))
        fmt.setBuffer(buf)

    pal = QgsPalLayerSettings()
    pal.fieldName = expr if use_expr else field
    pal.isExpression = use_expr
    pal.enabled = True
    with suppress(Exception):
        pal.placement = _placement_for(layer)
    pal.setFormat(fmt)

    layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()
    return True


def clear_labels(layer) -> None:
    layer.setLabelsEnabled(False)
    layer.setLabeling(None)
    layer.triggerRepaint()


def has_labels(layer) -> bool:
    try:
        return bool(layer.labelsEnabled())
    except Exception:
        return False
