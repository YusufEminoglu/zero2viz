# -*- coding: utf-8 -*-
"""Map-diagram options dialog.

Lets the user draw native QGIS diagrams (pie / bar / stacked / text) on every
feature of the active layer, using the numeric fields they tick and the
studio's current colour palette. Thin wrapper over ``core.diagrams`` — all the
QGIS renderer work lives there; this is only the form.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..core import diagrams
from ..core.profile import _is_id_name

_APPLY_QSS = (
    "QPushButton { background-color: #2a8f85; border: 1px solid #237a72;"
    " color: #ffffff; font-weight: 600; padding: 6px 14px; border-radius: 7px; }"
    "QPushButton:hover { background-color: #319c91; }"
    "QPushButton:disabled { background-color: #a9c8c4; border-color: #a9c8c4; }"
)


class MapDiagramDialog(QDialog):
    def __init__(self, layer, palette: list[str], iface, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.palette = palette or ["#2a8f85"]
        self.iface = iface
        self.setWindowTitle("Map diagrams — on-canvas charts")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            f"<b>{layer.name()}</b> — draw a diagram on every feature, "
            "coloured with the studio palette."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Type"))
        self.type_combo = QComboBox()
        for key in diagrams.DIAGRAM_TYPES:
            self.type_combo.addItem(diagrams.DIAGRAM_LABELS[key], key)
        row.addWidget(self.type_combo, 1)
        root.addLayout(row)

        root.addWidget(QLabel("Fields (numeric — slices / bars):"))
        self.field_list = QListWidget()
        self.field_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.field_list.setMaximumHeight(200)
        num_fields = diagrams.numeric_field_names(layer)
        picked = 0
        for name in num_fields:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # pre-tick meaningful numeric fields (skip id/fid/gid…), up to 4
            want = not _is_id_name(name) and picked < 4
            item.setCheckState(Qt.CheckState.Checked if want else Qt.CheckState.Unchecked)
            if want:
                picked += 1
            self.field_list.addItem(item)
        root.addWidget(self.field_list)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("Size (mm)"))
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(3.0, 60.0)
        self.size_spin.setValue(14.0)
        self.size_spin.setSingleStep(1.0)
        srow.addWidget(self.size_spin)
        srow.addStretch(1)
        root.addLayout(srow)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #5b6b73;")
        root.addWidget(self.status)

        btns = QHBoxLayout()
        self.apply_btn = QPushButton("Apply to layer")
        self.apply_btn.setStyleSheet(_APPLY_QSS)
        self.apply_btn.clicked.connect(self._apply)
        btns.addWidget(self.apply_btn)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Remove diagrams from this layer")
        self.clear_btn.clicked.connect(self._clear)
        btns.addWidget(self.clear_btn)
        btns.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        root.addLayout(btns)

        if not diagrams.layer_has_geometry(layer):
            self.status.setText("This layer has no geometry — diagrams need a "
                                "spatial layer.")
            self.apply_btn.setEnabled(False)
        elif not num_fields:
            self.status.setText("No numeric fields to chart on this layer.")
            self.apply_btn.setEnabled(False)

    def _checked_fields(self) -> list[str]:
        out = []
        for i in range(self.field_list.count()):
            item = self.field_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out

    def _apply(self) -> None:
        fields = self._checked_fields()
        if not fields:
            self.status.setText("Tick at least one numeric field.")
            return
        kind = self.type_combo.currentData()
        ok = diagrams.apply_diagram(
            self.layer, kind=kind, fields=fields, colors=self.palette,
            size_mm=self.size_spin.value())
        if not ok:
            self.status.setText("Could not apply the diagram.")
            return
        self._refresh_canvas()
        self.status.setText(
            f"Applied {diagrams.DIAGRAM_LABELS[kind].lower()} diagram "
            f"({len(fields)} field{'s' if len(fields) != 1 else ''}) to the canvas.")

    def _clear(self) -> None:
        diagrams.clear_diagram(self.layer)
        self._refresh_canvas()
        self.status.setText("Diagrams removed from this layer.")

    def _refresh_canvas(self) -> None:
        try:
            self.iface.layerTreeView().refreshLayerSymbology(self.layer.id())
        except Exception:
            pass
        try:
            self.iface.mapCanvas().refreshAllLayers()
        except Exception:
            pass
