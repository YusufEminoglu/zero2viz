# -*- coding: utf-8 -*-
"""02viz studio dock — the home of the chart studio.

Skeleton stage: branded shell with a status line. The chart builder
(data binding, engine selection, gallery, live preview) plugs into
the body area in upcoming versions; engines are imported lazily from
``..engines`` so the dock itself stays instant to open.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

_DOCK_QSS = """
QWidget#o2vizRoot { background: #fbfbfd; }
QLabel#o2vizTitle { font-size: 20px; font-weight: 700; color: #16323f; }
QLabel#o2vizTagline { color: #5b6b73; }
QFrame#o2vizCard {
    background: #ffffff;
    border: 1px solid #e3e7ec;
    border-radius: 10px;
}
QLabel#o2vizStatus { color: #5b6b73; padding: 4px 2px; }
"""


class StudioDockWidget(QDockWidget):
    chart_requested = pyqtSignal(str)  # engine/chart key, wired up later

    def __init__(self, iface, icon_dir: str, parent=None):
        super().__init__("02viz - Geospatial Visualization Studio", parent)
        self.iface = iface
        self.icon_dir = icon_dir
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._build_ui()

    def _build_ui(self) -> None:
        container = QWidget()
        container.setObjectName("o2vizRoot")
        container.setStyleSheet(_DOCK_QSS)
        root = QVBoxLayout(container)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("02viz")
        title.setObjectName("o2vizTitle")
        root.addWidget(title)

        tagline = QLabel("Geospatial Visualization Studio")
        tagline.setObjectName("o2vizTagline")
        root.addWidget(tagline)

        card = QFrame()
        card.setObjectName("o2vizCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        intro = QLabel(
            "The chart studio lives here: bind QGIS layers or external data "
            "to interactive, publication-quality charts rendered by multiple "
            "engines (Python, R, HTML/JavaScript).\n\n"
            "This is the v0.1.0 scaffold — the chart builder lands next."
        )
        intro.setWordWrap(True)
        card_layout.addWidget(intro)
        root.addWidget(card)

        root.addStretch(1)

        self.status = QLabel("Ready")
        self.status.setObjectName("o2vizStatus")
        root.addWidget(self.status)

        self.setWidget(container)

    def set_status(self, text: str) -> None:
        self.status.setText(text)
