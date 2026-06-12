# -*- coding: utf-8 -*-
"""02viz studio dock — the chart builder.

Data card (layer / selected-only / external table) + Chart card (type,
engine, theme, fields, aggregation, shaping) + embedded viewer with a
chart→map selection bridge. Spec assembly lives in ``_build_spec``;
rendering goes through the engine registry, so engines never touch Qt.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from qgis.PyQt.QtCore import Qt, QTimer
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

from ..core import datasource, profile as profiler, stats, transform
from ..engines import engines
from ..engines.base import DEFAULT_THEME, THEMES
from ..engines.dashboard import build_dashboard
from .bridge import SelectionBridge
from .webview import attach_title_listener, create_chart_view, run_js, show_html_file

# above this many selected features, skip the cross-filter highlight (the
# injected id list would dwarf any visual benefit)
MAX_HIGHLIGHT_IDS = 20000

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
    ("area", "Area chart"),
    ("scatter", "Scatter plot"),
    ("bubble", "Bubble chart"),
    ("histogram", "Histogram"),
    ("pie", "Pie / donut"),
    ("box", "Box plot"),
    ("heatmap", "Heatmap (matrix)"),
    ("treemap", "Treemap"),
    ("sunburst", "Sunburst"),
]

# which controls matter per chart type:
#   (y, group, value_size, aggregate, bins, topn_sort, stacked, trend)
_CONTROLS = {
    "bar":       (True,  True,  False, True,  False, True,  True,  False),
    "line":      (True,  True,  False, True,  False, True,  False, False),
    "area":      (True,  True,  False, True,  False, True,  True,  False),
    "scatter":   (True,  True,  False, False, False, False, False, True),
    "bubble":    (True,  True,  True,  False, False, False, False, True),
    "histogram": (False, False, False, False, True,  False, False, False),
    "pie":       (True,  False, False, True,  False, True,  False, False),
    "box":       (True,  True,  False, False, False, False, False, False),
    "heatmap":   (True,  False, True,  True,  False, False, False, False),
    "treemap":   (False, True,  True,  True,  False, False, False, False),
    "sunburst":  (False, True,  True,  True,  False, False, False, False),
}


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
        self._watched_layer = None
        self._suppress_refresh_until = 0.0
        self.bridge = SelectionBridge()
        self.bridge.on_selected = self._on_chart_drove_selection
        self._build_ui()

    # ───────────────────────── UI ─────────────────────────

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setProperty("class", "o2vizCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        head = QLabel(title)
        head.setProperty("class", "o2vizCardTitle")
        lay.addWidget(head)
        return card, lay

    def _field_combo(self) -> QgsFieldComboBox:
        combo = QgsFieldComboBox()
        combo.setAllowEmptyFieldName(True)
        return combo

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
        row = QHBoxLayout()
        self.selected_only = QCheckBox("Only selected features")
        row.addWidget(self.selected_only)
        self.auto_refresh = QCheckBox("Live: redraw on selection")
        self.auto_refresh.setToolTip(
            "Re-render the chart whenever the layer selection changes")
        row.addWidget(self.auto_refresh)
        data_lay.addLayout(row)
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

        self.theme_combo = QComboBox()
        for name in THEMES:
            self.theme_combo.addItem(name)
        self.theme_combo.setCurrentText(DEFAULT_THEME)
        form.addRow("Theme", self.theme_combo)

        self.x_combo = self._field_combo()
        form.addRow("X / Category", self.x_combo)
        self.y_combo = self._field_combo()
        form.addRow("Y", self.y_combo)
        self.group_combo = self._field_combo()
        self.group_combo.setToolTip("Split into one colored series per value (or sub-group for treemap/sunburst)")
        form.addRow("Group / Color", self.group_combo)
        self.value_combo = self._field_combo()
        self.value_combo.setToolTip("Bubble size, heatmap cell value or treemap weight")
        form.addRow("Value / Size", self.value_combo)

        self.agg_combo = QComboBox()
        self.agg_combo.addItems(list(stats.AGGREGATIONS))
        form.addRow("Aggregate", self.agg_combo)

        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(2, 200)
        self.bins_spin.setValue(20)
        form.addRow("Bins", self.bins_spin)

        self.topn_spin = QSpinBox()
        self.topn_spin.setRange(0, 200)
        self.topn_spin.setValue(0)
        self.topn_spin.setSpecialValueText("all")
        self.topn_spin.setToolTip("Keep the N largest categories, collapse the rest into 'Other'")
        form.addRow("Top N", self.topn_spin)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("natural order", "natural")
        self.sort_combo.addItem("value ↓", "value_desc")
        self.sort_combo.addItem("value ↑", "value_asc")
        form.addRow("Sort", self.sort_combo)

        flags = QHBoxLayout()
        self.stacked_check = QCheckBox("Stacked")
        flags.addWidget(self.stacked_check)
        self.trend_check = QCheckBox("Trend line")
        flags.addWidget(self.trend_check)
        self.link_check = QCheckBox("Click selects on map")
        self.link_check.setChecked(True)
        flags.addWidget(self.link_check)
        chart_lay.addLayout(form)
        chart_lay.addLayout(flags)
        root.addWidget(chart_card)

        # ── Actions ──
        btn_row = QHBoxLayout()
        self.render_btn = QPushButton("Render chart")
        self.render_btn.setStyleSheet(_RENDER_BTN_QSS)
        self.render_btn.clicked.connect(self._render)
        btn_row.addWidget(self.render_btn, 2)
        self.explore_btn = QPushButton("✨ Explore layer")
        self.explore_btn.setToolTip(
            "One click: profile every field and build a full interactive dashboard")
        self.explore_btn.setStyleSheet(
            "QPushButton { background-color: #16323f; border: 1px solid #16323f;"
            " color: #ffffff; font-weight: 600; padding: 7px 12px; border-radius: 8px; }"
            "QPushButton:hover { background-color: #1f4254; }")
        self.explore_btn.clicked.connect(self._explore)
        btn_row.addWidget(self.explore_btn, 2)
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
        for combo in (self.x_combo, self.y_combo, self.group_combo, self.value_combo):
            combo.setLayer(layer)
        self._watch_layer(layer)

    def _watch_layer(self, layer) -> None:
        if self._watched_layer is not None:
            try:
                self._watched_layer.selectionChanged.disconnect(self._on_selection_changed)
            except (RuntimeError, TypeError):
                pass
        self._watched_layer = layer
        if layer is not None:
            layer.selectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self, *_args) -> None:
        if self.auto_refresh.isChecked() and time.time() >= self._suppress_refresh_until:
            QTimer.singleShot(120, self._render)
            return
        # no re-render — cross-filter instead: dim chart items whose
        # features are not in the new canvas selection
        QTimer.singleShot(60, self._push_highlight)

    def _on_page_loaded(self, ok: bool) -> None:
        if ok:
            self._push_highlight()

    def _push_highlight(self) -> None:
        if self._view is None or not self.link_check.isChecked():
            return
        ids: list[int] = []
        if self._watched_layer is not None:
            try:
                ids = list(self._watched_layer.selectedFeatureIds())
            except RuntimeError:  # layer C++ object deleted
                ids = []
        if len(ids) > MAX_HIGHLIGHT_IDS:
            ids = []
        run_js(self._view_kind, self._view,
               "window.__o2vizHighlight && window.__o2vizHighlight(%s);"
               % (json.dumps(ids) if ids else "null"))

    def _on_chart_drove_selection(self) -> None:
        # a chart click is about to change the selection — don't re-render
        # the very chart the user is interacting with
        self._suppress_refresh_until = time.time() + 1.0

    def _sync_controls(self) -> None:
        kind = self.type_combo.currentData()
        y, group, value, agg, bins, topn_sort, stacked, trend = _CONTROLS[kind]
        self.y_combo.setEnabled(y)
        self.group_combo.setEnabled(group)
        self.value_combo.setEnabled(value)
        self.agg_combo.setEnabled(agg)
        self.bins_spin.setEnabled(bins)
        self.topn_spin.setEnabled(topn_sort)
        self.sort_combo.setEnabled(topn_sort)
        self.stacked_check.setEnabled(stacked)
        self.trend_check.setEnabled(trend)

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

    # ───────────────────────── spec assembly ─────────────────────────

    def _build_spec(self) -> dict | None:
        layer = self.layer_combo.currentLayer()
        if layer is None:
            self.set_status("Pick a layer first")
            return None
        kind = self.type_combo.currentData()
        x = self.x_combo.currentField()
        y = self.y_combo.currentField()
        group = self.group_combo.currentField() if self.group_combo.isEnabled() else ""
        value = self.value_combo.currentField() if self.value_combo.isEnabled() else ""
        agg = self.agg_combo.currentText()
        sel = self.selected_only.isChecked()

        fields = [f for f in {x, y, group, value} if f]
        if not fields:
            self.set_status("Pick at least an X field")
            return None
        try:
            cols, fids = datasource.columns_with_ids(layer, fields, sel)
        except ValueError as exc:
            self.set_status(str(exc))
            return None
        if not fids:
            self.set_status("No rows (empty selection?)")
            return None

        spec = {"type": kind, "title": layer.name(), "x_label": x, "y_label": y,
                "stacked": self.stacked_check.isChecked(),
                "theme": THEMES.get(self.theme_combo.currentText(), THEMES[DEFAULT_THEME])}

        builder = getattr(self, f"_spec_{kind}", None)
        data = builder(spec, cols, fids, x=x, y=y, group=group, value=value, agg=agg)
        if data is None:
            return None
        spec["data"] = data
        return spec

    # — per-type builders: return the spec["data"] dict, or None + status —

    def _agg_or(self, agg: str, fallback: str) -> str:
        return fallback if agg == "none" else agg

    def _cat_series(self, spec, cols, fids, *, x, y, group, agg):
        if not x:
            self.set_status("This chart needs an X / Category field")
            return None
        if agg == "none":
            if not y:
                self.set_status("Pick a Y field, or an aggregation like 'count'")
                return None
            cats = [transform._key(v) for v in cols[x]]
            vals = [stats.to_float(v) or 0.0 for v in cols[y]]
            ids = [[fid] for fid in fids]
            series = [{"name": y, "values": vals, "ids": ids}]
        elif group:
            spec["y_label"] = f"{agg}({y})" if agg != "count" else "count"
            cats, series = transform.pivot_rows(
                cols[x], cols[group], cols.get(y, []), fids, agg)
        else:
            if agg != "count" and not y:
                self.set_status(f"Aggregation '{agg}' needs a Y field")
                return None
            spec["y_label"] = f"{agg}({y})" if agg != "count" else "count"
            cats, vals, ids = transform.group_rows(cols[x], cols.get(y, []), fids, agg)
            series = [{"name": spec["y_label"], "values": vals, "ids": ids}]
        if len(series) == 1:
            cats, vals, ids = transform.sort_cats(
                cats, series[0]["values"], series[0]["ids"],
                self.sort_combo.currentData())
            cats, vals, ids = transform.topn_collapse(
                cats, vals, ids, self.topn_spin.value())
            series = [dict(series[0], values=vals, ids=ids)]
        return {"categories": cats, "series": series}

    def _spec_bar(self, spec, cols, fids, *, x, y, group, value, agg):
        return self._cat_series(spec, cols, fids, x=x, y=y, group=group, agg=agg)

    _spec_line = _spec_bar
    _spec_area = _spec_bar

    def _points(self, spec, cols, fids, *, x, y, group, size_field):
        if not x or not y:
            self.set_status("This chart needs numeric X and Y fields")
            return None
        sizes = (transform.bubble_sizes(cols[size_field])
                 if size_field else [None] * len(fids))
        buckets: dict[str, list] = {}
        order: list[str] = []
        all_points = []
        for i in range(len(fids)):
            xf, yf = stats.to_float(cols[x][i]), stats.to_float(cols[y][i])
            if xf is None or yf is None:
                continue
            point = [xf, yf, sizes[i], fids[i]]
            all_points.append(point)
            key = transform._key(cols[group][i]) if group else ""
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(point)
        if not all_points:
            self.set_status("No numeric X/Y pairs found")
            return None
        series = [{"name": k or spec["y_label"], "points": buckets[k]} for k in order]
        trend = (transform.linreg_endpoints(all_points)
                 if self.trend_check.isChecked() else None)
        return {"series": series, "trend": trend}

    def _spec_scatter(self, spec, cols, fids, *, x, y, group, value, agg):
        return self._points(spec, cols, fids, x=x, y=y, group=group, size_field=None)

    def _spec_bubble(self, spec, cols, fids, *, x, y, group, value, agg):
        if not value:
            self.set_status("Bubble chart needs a Value / Size field")
            return None
        return self._points(spec, cols, fids, x=x, y=y, group=group, size_field=value)

    def _spec_histogram(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x:
            self.set_status("Histogram needs an X field (numeric)")
            return None
        labels, counts = stats.histogram(cols[x], self.bins_spin.value())
        if not labels:
            self.set_status(f"No numeric values in '{x}'")
            return None
        spec["y_label"] = "count"
        return {"categories": labels, "values": counts}

    def _spec_pie(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x:
            self.set_status("Pie needs an X / Category field")
            return None
        how = self._agg_or(agg, "count")
        if how != "count" and not y:
            self.set_status(f"Aggregation '{how}' needs a Y field")
            return None
        cats, vals, ids = transform.group_rows(cols[x], cols.get(y, []), fids, how)
        cats, vals, ids = transform.sort_cats(cats, vals, ids, self.sort_combo.currentData())
        cats, vals, ids = transform.topn_collapse(cats, vals, ids, self.topn_spin.value())
        return {"categories": cats, "values": vals, "ids": ids}

    def _spec_box(self, spec, cols, fids, *, x, y, group, value, agg):
        if not y:
            self.set_status("Box plot needs a Y field (numeric)")
            return None
        source = cols[group] if group else (cols[x] if x else None)
        if source is not None:
            buckets: dict[str, list] = {}
            order: list[str] = []
            for i, raw in enumerate(source):
                key = transform._key(raw)
                if key not in buckets:
                    buckets[key] = []
                    order.append(key)
                buckets[key].append(cols[y][i])
        else:
            order = [y]
            buckets = {y: cols[y]}
        groups, box = [], []
        for key in order:
            st = stats.boxplot_stats(buckets[key])
            if st is not None:
                groups.append(key)
                box.append(st)
        if not box:
            self.set_status(f"No numeric values in '{y}'")
            return None
        return {"groups": groups, "stats": box}

    def _spec_heatmap(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x or not y:
            self.set_status("Heatmap needs X and Y category fields")
            return None
        how = self._agg_or(agg, "count")
        if how != "count" and not value:
            self.set_status(f"Aggregation '{how}' needs a Value field")
            return None
        x_cats, y_cats, cells, vmin, vmax = transform.heatmap_rows(
            cols[x], cols[y], cols.get(value, []), how)
        return {"x_cats": x_cats, "y_cats": y_cats, "cells": cells,
                "vmin": vmin, "vmax": vmax}

    def _spec_treemap(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x:
            self.set_status("This chart needs an X field as the main grouping")
            return None
        how = self._agg_or(agg, "count")
        if how != "count" and not value:
            self.set_status(f"Aggregation '{how}' needs a Value field")
            return None
        nodes = transform.tree_rows(cols[x], cols.get(group, []),
                                    cols.get(value, []), how)
        return {"nodes": nodes}

    _spec_sunburst = _spec_treemap

    # ───────────────────────── render / explore / export ─────────────────────────

    def _current_theme(self) -> dict:
        return THEMES.get(self.theme_combo.currentText(), THEMES[DEFAULT_THEME])

    def _show_html(self, html: str, status: str) -> None:
        if self._tmp_dir is None:
            self._tmp_dir = tempfile.mkdtemp(prefix="o2viz_")
        path = os.path.join(self._tmp_dir, f"chart_{int(time.time() * 1000)}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        self._last_html = html

        if self._view is None and self._view_kind is None:
            self._view_kind, self._view = create_chart_view(self)
            if self._view is not None:
                attach_title_listener(self._view_kind, self._view, self.bridge.handle_title)
                # a fresh page should immediately reflect the current canvas
                # selection (same signal on QWebView and QWebEngineView)
                self._view.loadFinished.connect(self._on_page_loaded)
                self._view_placeholder.hide()
                self._view.setMinimumHeight(300)
                self._view_slot.addWidget(self._view, 1)
        self.bridge.bind(self.layer_combo.currentLayer()
                         if self.link_check.isChecked() else None)
        embedded = show_html_file(self._view_kind, self._view, path)
        self.export_btn.setEnabled(True)
        where = "" if embedded else " (no web view in this QGIS build — opened in your browser)"
        self.set_status(status + where)

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
        self._show_html(html, f"Rendered {spec['type']} · {engine.label}")

    def _explore(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is None:
            self.set_status("Pick a layer first")
            return
        try:
            prof = profiler.build_profile(layer, self.selected_only.isChecked(),
                                          self._current_theme())
            if not prof["tiles"]:
                self.set_status("Nothing chartable found in this layer's fields")
                return
            html = build_dashboard(prof, self._current_theme())
        except Exception as exc:
            self.set_status(f"Explore failed: {exc}")
            return
        self._show_html(html, f"Explored {layer.name()}: {len(prof['tiles'])} charts, "
                              f"{len(prof['insights'])} insights")

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
