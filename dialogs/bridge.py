# -*- coding: utf-8 -*-
"""Chart → map selection bridge (title transport).

The chart page encodes clicked feature ids into ``document.title``
(``"o2viz-select:<id,id,...>:<seq>"``, written by ``__o2vizSelect`` in
``engines.base.BRIDGE_JS``); the dock forwards every titleChanged
notification to :meth:`SelectionBridge.handle_title`. We resolve the
bound layer by id — never by reference, the layer may have been
removed — and select those features on the canvas.

Why the page title? QGIS's legacy QtWebKit fork crashes with an access
violation inside WebCore when a Python object is exposed through
``addToJavaScriptWindowObject`` during page commit (observed on QGIS
3.44 / Qt 5.15), and ``QWebChannel`` only exists on WebEngine. The page
title is the one transport that behaves identically on both web stacks
— and is harmlessly inert when the exported HTML is opened in a plain
browser.
"""
from __future__ import annotations

from qgis.core import QgsProject

from ..engines.base import TITLE_PREFIX


class SelectionBridge:
    def __init__(self):
        self._layer_id: str | None = None
        self.on_selected = None  # callback fired just before selecting (loop guard)

    def bind(self, layer) -> None:
        self._layer_id = layer.id() if layer is not None else None

    def handle_title(self, title: str) -> None:
        """titleChanged slot: ignore ordinary titles, decode selection ones."""
        if not title or not title.startswith(TITLE_PREFIX):
            return
        payload = title[len(TITLE_PREFIX):]
        ids_csv, sep, _seq = payload.rpartition(":")
        self.select(ids_csv if sep else payload)

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
        if not ids:
            return
        if self.on_selected:
            self.on_selected()
        layer.selectByIds(ids)
