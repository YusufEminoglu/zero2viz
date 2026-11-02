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

from ..engines.base import parse_select_title


class SelectionBridge:
    def __init__(self):
        self._layer_id: str | None = None
        self.on_selected = None  # callback fired just before selecting (loop guard)

    def bind(self, layer) -> None:
        self._layer_id = layer.id() if layer is not None else None

    def handle_title(self, title: str) -> None:
        """titleChanged slot: only the exact message shape the plugin's own
        page writes (``o2viz-select:<int,...>:<seq>``) selects anything; any
        other title, including a crafted one that merely starts with the
        prefix, is ignored."""
        ids = parse_select_title(title)
        if ids:
            self.select_ids(ids)

    def select(self, ids_csv: str) -> None:
        """Select from a comma-separated id list (integers only)."""
        try:
            ids = [int(part) for part in ids_csv.split(",") if part.strip()]
        except ValueError:
            return
        self.select_ids(ids)

    def select_ids(self, ids: list[int]) -> None:
        if not self._layer_id or not ids:
            return
        layer = QgsProject.instance().mapLayer(self._layer_id)
        if layer is None:
            return
        if self.on_selected:
            self.on_selected()
        layer.selectByIds(ids)
