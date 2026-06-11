# -*- coding: utf-8 -*-
"""Chart → map selection bridge.

The chart HTML calls ``o2vizBridge.select("1,2,3")`` (directly via the
QtWebKit window object, or through a QWebChannel on QtWebEngine); we
resolve the bound layer by id — never by reference, the layer may have
been removed — and select those features on the canvas.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import QObject, pyqtSlot
from qgis.core import QgsProject


class SelectionBridge(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layer_id: str | None = None
        self.on_selected = None  # callback fired just before selecting (loop guard)

    def bind(self, layer) -> None:
        self._layer_id = layer.id() if layer is not None else None

    @pyqtSlot(str)
    def select(self, ids_csv: str) -> None:
        if not self._layer_id:
            return
        layer = QgsProject.instance().mapLayer(self._layer_id)
        if layer is None:
            return
        try:
            ids = [int(part) for part in ids_csv.split(",") if part.strip()]
        except ValueError:
            return
        if self.on_selected:
            self.on_selected()
        layer.selectByIds(ids)
