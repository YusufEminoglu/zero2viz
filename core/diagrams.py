# -*- coding: utf-8 -*-
"""On-canvas feature diagrams — QGIS native ``QgsDiagramRenderer``.

This is the "layer diagram options" side of 02viz: instead of one chart in
the dock, draw a tiny pie / bar / stacked-bar / text diagram *on every
feature* directly on the map canvas, sized in millimetres and coloured with
the same palette the studio uses. Pure QGIS API (no web stack), so the
diagrams print, export to layout and follow the layer like any symbology.

Everything here is headless-testable: ``apply_diagram`` only touches the
layer's diagram renderer + layer settings; ``layer.diagramsEnabled()`` and
``layer.diagramRenderer()`` reflect the result without a canvas.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import QSizeF
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    QgsDiagramLayerSettings,
    QgsDiagramSettings,
    QgsHistogramDiagram,
    QgsPieDiagram,
    QgsSingleCategoryDiagramRenderer,
    QgsTextDiagram,
    QgsWkbTypes,
)

try:  # added in QGIS 3.14, present on the 3.28 floor — guard anyway
    from qgis.core import QgsStackedBarDiagram
except ImportError:  # pragma: no cover
    QgsStackedBarDiagram = None

try:  # render-unit enum location differs across QGIS lines
    from qgis.core import QgsUnitTypes
    _MM = QgsUnitTypes.RenderMillimeters
except (ImportError, AttributeError):  # pragma: no cover - QGIS 4 scoped enums
    from qgis.core import Qgis
    _MM = Qgis.RenderUnit.Millimeters

# diagram-type key → factory; "bar" is QGIS's histogram (side-by-side bars)
DIAGRAM_TYPES = ("pie", "bar", "stacked", "text")
DIAGRAM_LABELS = {
    "pie": "Pie",
    "bar": "Bar",
    "stacked": "Stacked bar",
    "text": "Text",
}


def _diagram_for(kind: str):
    if kind == "pie":
        return QgsPieDiagram()
    if kind == "bar":
        return QgsHistogramDiagram()
    if kind == "stacked" and QgsStackedBarDiagram is not None:
        return QgsStackedBarDiagram()
    if kind == "text":
        return QgsTextDiagram()
    return QgsHistogramDiagram()  # safe fallback


def _placement_for(layer):
    """Geometry-appropriate placement, scoped-enum safe (Qt5/Qt6)."""
    P = QgsDiagramLayerSettings
    try:
        over, around, line = P.OverPoint, P.AroundPoint, P.Line
    except AttributeError:  # QGIS 4 scoped enums
        over = P.Placement.OverPoint
        around = P.Placement.AroundPoint
        line = P.Placement.Line
    gtype = layer.geometryType()
    if gtype == QgsWkbTypes.PointGeometry:
        return around
    if gtype == QgsWkbTypes.LineGeometry:
        return line
    return over  # polygons: centroid


def layer_has_geometry(layer) -> bool:
    """Diagrams need somewhere to draw — attribute-only tables have none."""
    try:
        return layer.geometryType() in (
            QgsWkbTypes.PointGeometry,
            QgsWkbTypes.LineGeometry,
            QgsWkbTypes.PolygonGeometry,
        )
    except Exception:
        return False


def numeric_field_names(layer) -> list[str]:
    """Numeric fields are the only ones a diagram can size bars/slices by."""
    out = []
    for field in layer.fields():
        try:
            if field.isNumeric():
                out.append(field.name())
        except Exception:
            pass
    return out


def apply_diagram(layer, *, kind: str, fields: list[str], colors: list[str],
                  size_mm: float = 14.0, opacity: float = 1.0,
                  text_color: str = "#16323f", line_color: str = "#ffffff") -> bool:
    """Attach a diagram renderer to ``layer``. Returns True on success.

    ``fields`` are the numeric attributes that become slices / bars;
    ``colors`` recolours them in order (cycled if shorter than ``fields``).
    """
    if not fields or not layer_has_geometry(layer):
        return False
    palette = colors or ["#2a8f85"]

    settings = QgsDiagramSettings()
    settings.enabled = True
    settings.sizeType = _MM
    settings.size = QSizeF(size_mm, size_mm)
    settings.font = QFont("Segoe UI", 8)
    settings.categoryAttributes = [f'"{name}"' for name in fields]
    try:  # categoryLabels exists on recent QGIS; harmless to skip otherwise
        settings.categoryLabels = list(fields)
    except Exception:
        pass
    settings.categoryColors = [QColor(palette[i % len(palette)])
                               for i in range(len(fields))]
    settings.backgroundColor = QColor(0, 0, 0, 0)
    settings.penColor = QColor(line_color)
    settings.penWidth = 0.3
    settings.minimumScale = -1
    settings.maximumScale = -1
    settings.opacity = max(0.0, min(1.0, opacity))
    if kind == "text":
        settings.font = QFont("Segoe UI", 9)
        try:
            settings.textColor = QColor(text_color)
        except Exception:
            pass

    renderer = QgsSingleCategoryDiagramRenderer()
    renderer.setDiagram(_diagram_for(kind))
    renderer.setDiagramSettings(settings)
    layer.setDiagramRenderer(renderer)

    dls = QgsDiagramLayerSettings()
    dls.setPlacement(_placement_for(layer))
    dls.setShowAllDiagrams(True)
    layer.setDiagramLayerSettings(dls)

    layer.triggerRepaint()
    return True


def clear_diagram(layer) -> None:
    """Remove any diagram from the layer and refresh it."""
    layer.setDiagramRenderer(None)
    dls = QgsDiagramLayerSettings()
    dls.setShowAllDiagrams(False)
    layer.setDiagramLayerSettings(dls)
    layer.triggerRepaint()


def has_diagram(layer) -> bool:
    try:
        return layer.diagramsEnabled() and layer.diagramRenderer() is not None
    except Exception:
        return False
