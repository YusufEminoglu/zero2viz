# -*- coding: utf-8 -*-
"""02viz studio dock — the chart builder.

Data card (layer / selected-only / external table) + Chart card (type,
fields, aggregation, bins) + embedded viewer. Spec assembly lives in
``_build_spec``; rendering goes through the engine registry so future
engines (Plotly, Vega-Lite, R) plug in without touching this UI flow.
"""
from __future__ import annotations

import os
import tempfile
import time

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox

from ..core import datasource, stats
from ..engines import engines
from .webview import create_chart_view, show_html_file

_DOCK_QSS = """
QWidget#o2vizRoot { background: #fbfbfd; }
QLabel#o2vizTitle { font-size: 18px; font-weight: 700; color: #16323f; }
QLabel#o2vizTagline { color: #5b6b73; }
QFrame.o2vizCard {
    background: #ffffff;
    border: 1px solid #e3e7ec;
    border-radius: 10px;
}
QLabel.o2vizCardTitle { font-weight: 600; color: #16323f; }
QLabel#o2vizStatus { color: #5b6b73; padding: 2px; }
"""
_RENDER_BTN_QSS = (
    "QPushButton { background-color: #2a8f85; border: 1px solid #237a72;"
    " color: #ffffff; font-weight: 600; padding: 7px 14px; border-radius: 8px; }"
    "QPushButton:hover { background-color: #319c91; }"
    "QPushButton:disabled { background-color: #a9c8c4; border-color: #a9c8c4; }"
)

CHART_TYPES = [
    ("bar", "Bar chart"),
    ("line", "Line chart"),
    ("scatter", "Scatter plot"),
    ("histogram", "Histogram"),
    ("pie", "Pie / donut"),
    ("box", "Box plot"),
]


def _vector_filter():
    """Scoped-enum-safe vector filter for QgsMapLayerComboBox (Qt5/Qt6)."""
    from qgis.core import QgsMapLayerProxyModel

    try:
        return QgsMapLayerProxyModel.VectorLayer
    except AttributeError:  # QGIS 4 scoped enums
        return QgsMapLayerProxyModel.Filter.VectorLayer


class StudioDockWidget(QDockWidget):
    def __init__(self, iface, icon_dir: str, parent=None):
        super().__init__("02viz - Geospatial Visualization Studio", parent)
        self.iface = iface
        self.icon_dir = icon_dir
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._view_kind: str | None = None
        self._view = None
        self._view_slot: QVBoxLayout | None = None
        self._last_html: str | None = None
        self._tmp_dir: str | None = None
        self._build_ui()

    # ───────────────────────── UI ─────────────────────────

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setProperty("class", "o2vizCard")
        card.setObjectName("card_" + title)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        head = QLabel(title)
        head.setProperty("class", "o2vizCardTitle")
        lay.addWidget(head)
        return card, lay

    def _build_ui(self) -> None:
        container = QWidget()
        container.setObjectName("o2vizRoot")
        container.setStyleSheet(_DOCK_QSS)
        root = QVBoxLayout(container)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("02viz")
        title.setObjectName("o2vizTitle")
        root.addWidget(title)
        tagline = QLabel("Geospatial Visualization Studio")
        tagline.setObjectName("o2vizTagline")
        root.addWidget(tagline)

        # ── Data card ──
        data_card, data_lay = self._card("Data")
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(_vector_filter())
        self.layer_combo.layerChanged.connect(self._on_layer_changed)
        data_lay.addWidget(self.layer_combo)
        self.selected_only = QCheckBox("Only selected features")
        data_lay.addWidget(self.selected_only)
        ext_btn = QPushButton("Load external table…")
        ext_btn.setToolTip("Open a CSV/XLSX/ODS table — it joins the layer list above")
        ext_btn.clicked.connect(self._load_external)
        data_lay.addWidget(ext_btn)
        root.addWidget(data_card)

        # ── Chart card ──
        chart_card, chart_lay = self._card("Chart")
        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        self.type_combo = QComboBox()
        for key, label in CHART_TYPES:
            self.type_combo.addItem(label, key)
        self.type_combo.currentIndexChanged.connect(self._sync_controls)
        form.addRow("Type", self.type_combo)

        self.engine_combo = QComboBox()
        for eng in engines():
            self.engine_combo.addItem(eng.label, eng.id)
        form.addRow("Engine", self.engine_combo)

        self.x_combo = QgsFieldComboBox()
        self.x_combo.setAllowEmptyFieldName(True)
        form.addRow("X field", self.x_combo)

        self.y_combo = QgsFieldComboBox()
        self.y_combo.setAllowEmptyFieldName(True)
        form.addRow("Y field", self.y_combo)

        self.agg_combo = QComboBox()
        self.agg_combo.addItems(list(stats.AGGREGATIONS))
        form.addRow("Aggregate", self.agg_combo)

        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(2, 200)
        self.bins_spin.setValue(20)
        form.addRow("Bins", self.bins_spin)

        chart_lay.addLayout(form)
        root.addWidget(chart_card)

        # ── Actions ──
        btn_row = QHBoxLayout()
        self.render_btn = QPushButton("Render chart")
        self.render_btn.setStyleSheet(_RENDER_BTN_QSS)
        self.render_btn.clicked.connect(self._render)
        btn_row.addWidget(self.render_btn, 2)
        self.export_btn = QPushButton("Export HTML…")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_html)
        btn_row.addWidget(self.export_btn, 1)
        root.addLayout(btn_row)

        # ── Viewer slot ──
        self._view_slot = QVBoxLayout()
        self._view_placeholder = QLabel(
            "Pick a layer, choose a chart type and hit Render."
        )
        self._view_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view_placeholder.setStyleSheet("color: #8d99ae; padding: 22px;")
        self._view_slot.addWidget(self._view_placeholder)
        root.addLayout(self._view_slot, 1)

        self.status = QLabel("Ready")
        self.status.setObjectName("o2vizStatus")
        root.addWidget(self.status)

        self.setWidget(container)
        self._on_layer_changed(self.layer_combo.currentLayer())
        self._sync_controls()

    # ───────────────────────── wiring ─────────────────────────

    def _on_layer_changed(self, layer) -> None:
        self.x_combo.setLayer(layer)
        self.y_combo.setLayer(layer)

    def _sync_controls(self) -> None:
        kind = self.type_combo.currentData()
        self.y_combo.setEnabled(kind != "histogram")
        self.agg_combo.setEnabled(kind in ("bar", "line", "pie"))
        self.bins_spin.setEnabled(kind == "histogram")

    def _load_external(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load external table", "",
            "Tables (*.csv *.xlsx *.ods *.gpkg *.dbf);;All files (*.*)")
        if not path:
            return
        layer = datasource.load_table(path)
        if layer is None:
            self.set_status(f"Could not read: {os.path.basename(path)}")
            return
        self.layer_combo.setLayer(layer)
        self.set_status(f"Loaded table: {layer.name()} ({layer.featureCount()} rows)")

    # ───────────────────────── spec / render ─────────────────────────

    def _build_spec(self) -> dict | None:
        layer = self.layer_combo.currentLayer()
        if layer is None:
            self.set_status("Pick a layer first")
            return None
        kind = self.type_combo.currentData()
        x_field = self.x_combo.currentField()
        y_field = self.y_combo.currentField()
        agg = self.agg_combo.currentText()
        sel = self.selected_only.isChecked()

        def col(*names):
            return datasource.columns(layer, [n for n in names if n], sel)

        title = layer.name()
        spec = {"type": kind, "title": title, "x_label": x_field, "y_label": y_field}

        if kind == "histogram":
            if not x_field:
                self.set_status("Histogram needs an X field (numeric)")
                return None
            labels, counts = stats.histogram(col(x_field)[x_field], self.bins_spin.value())
            if not labels:
                self.set_status(f"No numeric values in '{x_field}'")
                return None
            spec["y_label"] = "count"
            spec["data"] = {"categories": labels, "values": counts}
            return spec

        if kind == "scatter":
            if not x_field or not y_field:
                self.set_status("Scatter needs both X and Y fields")
                return None
            cols = col(x_field, y_field)
            points = []
            for xv, yv in zip(cols[x_field], cols[y_field]):
                xf, yf = stats.to_float(xv), stats.to_float(yv)
                if xf is not None and yf is not None:
                    points.append([xf, yf])
            if not points:
                self.set_status("No numeric X/Y pairs found")
                return None
            spec["data"] = {"points": points}
            return spec

        if kind == "box":
            if not y_field:
                self.set_status("Box plot needs a Y field (numeric)")
                return None
            cols = col(x_field, y_field)
            if x_field:
                groups: dict[str, list] = {}
                order: list[str] = []
                for xv, yv in zip(cols[x_field], cols[y_field]):
                    key = "(null)" if xv is None else str(xv)
                    if key not in groups:
                        groups[key] = []
                        order.append(key)
                    groups[key].append(yv)
            else:
                order = [y_field]
                groups = {y_field: cols[y_field]}
            names, box_stats = [], []
            for key in order:
                st = stats.boxplot_stats(groups[key])
                if st is not None:
                    names.append(key)
                    box_stats.append(st)
            if not box_stats:
                self.set_status(f"No numeric values in '{y_field}'")
                return None
            spec["data"] = {"groups": names, "stats": box_stats}
            return spec

        # bar / line / pie
        if not x_field:
            self.set_status(f"{kind.capitalize()} needs an X field")
            return None
        if agg == "none":
            if not y_field:
                self.set_status("Pick a Y field, or choose an aggregation like 'count'")
                return None
            cols = col(x_field, y_field)
            cats = ["(null)" if v is None else str(v) for v in cols[x_field]]
            vals = [stats.to_float(v) for v in cols[y_field]]
            vals = [0.0 if v is None else v for v in vals]
        else:
            if agg != "count" and not y_field:
                self.set_status(f"Aggregation '{agg}' needs a Y field")
                return None
            cols = col(x_field, y_field)
            cats, vals = stats.aggregate(
                cols[x_field], cols.get(y_field, []), agg)
            spec["y_label"] = f"{agg}({y_field})" if agg != "count" else "count"
        if not cats:
            self.set_status("No rows to plot")
            return None
        spec["data"] = {"categories": cats, "values": vals}
        return spec

    def _render(self) -> None:
        try:
            spec = self._build_spec()
            if spec is None:
                return
            engine = engines()[max(0, self.engine_combo.currentIndex())]
            html = engine.build_html(spec)
        except Exception as exc:
            self.set_status(f"Chart failed: {exc}")
            return

        if self._tmp_dir is None:
            self._tmp_dir = tempfile.mkdtemp(prefix="o2viz_")
        path = os.path.join(self._tmp_dir, f"chart_{int(time.time() * 1000)}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        self._last_html = html

        if self._view is None and self._view_kind is None:
            self._view_kind, self._view = create_chart_view(self)
            if self._view is not None:
                self._view_placeholder.hide()
                self._view.setMinimumHeight(280)
                self._view_slot.addWidget(self._view, 1)
        embedded = show_html_file(self._view_kind, self._view, path)
        self.export_btn.setEnabled(True)
        n = self._spec_row_count(spec)
        where = "" if embedded else " (no web view in this QGIS build — opened in your browser)"
        self.set_status(f"Rendered {spec['type']} · {n} item(s){where}")

    @staticmethod
    def _spec_row_count(spec: dict) -> int:
        data = spec.get("data", {})
        for key in ("categories", "points", "groups"):
            if key in data:
                return len(data[key])
        return 0

    def _export_html(self) -> None:
        if not self._last_html:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export chart as HTML", "02viz_chart.html", "HTML (*.html)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._last_html)
        self.set_status(f"Exported: {os.path.basename(path)}")

    def set_status(self, text: str) -> None:
        self.status.setText(text)
