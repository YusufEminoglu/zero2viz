# -*- coding: utf-8 -*-
"""Custom colour palette editor.

A compact dialog: a row of clickable colour swatches the user can edit
(QColorDialog), reorder-by-add/remove, seeded from whatever palette is
currently active. Returns a list of ``#rrggbb`` strings that the dock
writes straight into ``spec["theme"]["palette"]`` — so a custom palette
recolours ECharts, Plotly and Vega-Lite identically, exactly like the
built-in palettes.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MIN_COLORS = 1
MAX_COLORS = 16
_DEFAULT = "#2a8f85"


class PaletteEditor(QDialog):
    """Edit a list of hex colours. ``editor.palette()`` returns the result."""

    def __init__(self, colors=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom colour palette")
        self.setMinimumWidth(360)
        self._colors: list[str] = [self._norm(c) for c in (colors or [])] or [_DEFAULT]

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Click a swatch to change its colour. The order is the series "
            "order in every chart."))

        self._swatch_host = QWidget()
        self._swatch_row = QHBoxLayout(self._swatch_host)
        self._swatch_row.setContentsMargins(0, 4, 0, 4)
        self._swatch_row.setSpacing(6)
        root.addWidget(self._swatch_host)

        tools = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add)
        tools.addWidget(add_btn)
        self._remove_btn = QPushButton("− Remove")
        self._remove_btn.clicked.connect(self._remove)
        tools.addWidget(self._remove_btn)
        tools.addStretch(1)
        root.addLayout(tools)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._rebuild()

    # ───────────────────── helpers ─────────────────────

    @staticmethod
    def _norm(c) -> str:
        col = QColor(c)
        return col.name() if col.isValid() else _DEFAULT

    def palette(self) -> list[str]:
        return list(self._colors)

    def _rebuild(self) -> None:
        while self._swatch_row.count():
            item = self._swatch_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, color in enumerate(self._colors):
            btn = QPushButton()
            btn.setFixedSize(30, 30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(color)
            btn.setStyleSheet(
                f"QPushButton {{ background: {color}; border: 1px solid #00000033;"
                f" border-radius: 6px; }}"
                f"QPushButton:hover {{ border: 2px solid #16323f; }}")
            btn.clicked.connect(lambda _=False, idx=i: self._edit(idx))
            self._swatch_row.addWidget(btn)
        self._swatch_row.addStretch(1)
        self._remove_btn.setEnabled(len(self._colors) > MIN_COLORS)

    def _edit(self, idx: int) -> None:
        chosen = QColorDialog.getColor(
            QColor(self._colors[idx]), self, "Pick a colour")
        if chosen.isValid():
            self._colors[idx] = chosen.name()
            self._rebuild()

    def _add(self) -> None:
        if len(self._colors) >= MAX_COLORS:
            return
        chosen = QColorDialog.getColor(QColor(_DEFAULT), self, "Add a colour")
        if chosen.isValid():
            self._colors.append(chosen.name())
            self._rebuild()

    def _remove(self) -> None:
        if len(self._colors) > MIN_COLORS:
            self._colors.pop()
            self._rebuild()
