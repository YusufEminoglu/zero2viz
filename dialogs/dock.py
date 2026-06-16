# -*- coding: utf-8 -*-
"""02viz studio dock — charts, map diagrams and labels under one roof.

A shared Data card (layer / selected-only / external table) above three tabs:
**Charts** (engine/type/theme/fields/shaping → embedded viewer with a
chart→map selection bridge; spec assembly in ``_build_spec``), **Map
diagrams** (native on-canvas diagrams with optional normalisation) and
**Labels** (expression-driven, formatted, multi-line labels). A header
**Guide** button shows the offline user guide and **Suggest** asks the
offline assistant for the best chart. Rendering goes through the engine
registry, so engines never touch Qt; the pure logic lives in ``core``.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox

from ..core import (
    assistant, datasource, diagrams, expressions, labels,
    profile as profiler, requirements, stats, transform,
)
from ..engines import engines
from ..engines.base import DEFAULT_THEME, PALETTES, THEMES, webkit_fallback_page
from ..engines.dashboard import build_dashboard
from ..engines.guide import build_guide_html
from .bridge import SelectionBridge
from .webview import attach_title_listener, create_chart_view, run_js, show_html_file

# above this many selected features, skip the cross-filter highlight (the
# injected id list would dwarf any visual benefit)
MAX_HIGHLIGHT_IDS = 20000

# sentinel entry in the Colors combo that opens the custom palette editor
CUSTOM_PALETTE_LABEL = "Custom…"

# The studio has its own light visual identity (light root, white cards). On
# QGIS 3 (Qt5) the host palette is light too, so unstyled child widgets looked
# fine by accident. On QGIS 4 (Qt6) the host palette is often dark: every
# colour we DON'T pin is then inherited from it, so the combo popups paint
# near-black and the field labels/checkboxes turn into light-on-white ghosts
# (the "siyah dropdown + okunmayan yazı" bug). The remedy is to pin every text
# and input colour here, so the panel reads identically under any host theme.
_DOCK_QSS = """
QWidget#o2vizRoot { background: #fbfbfd; }
QWidget#o2vizTabPage { background: #ffffff; }
QLabel#o2vizTitle { font-size: 18px; font-weight: 700; color: #16323f; }
QLabel#o2vizTagline { color: #5b6b73; }
QFrame.o2vizCard {
    background: #ffffff;
    border: 1px solid #e3e7ec;
    border-radius: 10px;
}
QLabel.o2vizCardTitle { font-weight: 600; color: #16323f; }
QLabel#o2vizStatus { color: #5b6b73; padding: 2px; }
QTabWidget::pane { border: 1px solid #e3e7ec; border-radius: 8px; top: -1px;
                   background: #ffffff; }
QTabBar::tab { background: #eef1f4; color: #5b6b73; padding: 6px 15px;
               margin-right: 2px; border-top-left-radius: 7px;
               border-top-right-radius: 7px; }
QTabBar::tab:selected { background: #ffffff; color: #16323f; font-weight: 600; }
QTabBar::tab:hover { color: #16323f; }

/* ── text + form labels (pinned dark so they never inherit a light palette
      text colour and vanish on the white cards) ── */
QLabel { color: #2c3e46; background: transparent; }
QCheckBox { color: #2c3e46; background: transparent; spacing: 6px; }
QCheckBox:disabled { color: #9aa6ae; }

/* ── inputs: white field, dark text, teal selection — independent of the host
      palette so the dropdown popup is never black again ── */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QListWidget {
    background: #ffffff;
    color: #16323f;
    border: 1px solid #cbd3da;
    border-radius: 6px;
    padding: 3px 6px;
    selection-background-color: #2a8f85;
    selection-color: #ffffff;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #2a8f85;
}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled {
    background: #eef1f3; color: #9aa6ae; border-color: #dde2e6;
}
/* the drop-down list itself — the surface the user saw as solid black */
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #16323f;
    border: 1px solid #cbd3da;
    selection-background-color: #2a8f85;
    selection-color: #ffffff;
    outline: 0;
}
QComboBox QAbstractItemView::item { min-height: 22px; padding: 2px 4px; }
QListWidget::item { color: #16323f; }
QListWidget::item:selected { background: #2a8f85; color: #ffffff; }

/* ── secondary buttons (Load table / Clear / ↗): the primary ones set their
      own teal style in code, which wins over this neutral default ── */
QPushButton {
    background: #eef1f4; color: #1f333d;
    border: 1px solid #cbd3da; border-radius: 6px; padding: 5px 10px;
}
QPushButton:hover { background: #e4e9ed; }
QPushButton:disabled { background: #f2f4f6; color: #9aa6ae; border-color: #e2e6ea; }

QToolTip { background: #16323f; color: #ffffff; border: 1px solid #16323f;
           padding: 4px 6px; }
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
    ("errorband", "Mean ± σ band"),
    ("errorbar", "Mean ± σ bars"),
    ("density", "Density (KDE)"),
    ("violin", "Violin plot"),
    ("radar", "Radar / spider"),
    ("pareto", "Pareto (80/20)"),
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
    "errorband": (True,  True,  False, False, False, False, False, False),
    "errorbar":  (True,  True,  False, False, False, False, False, False),
    "density":   (False, True,  False, False, False, False, False, False),
    "violin":    (True,  True,  False, False, False, False, False, False),
    "radar":     (True,  True,  False, True,  False, False, False, False),
    "pareto":    (True,  False, False, True,  False, True,  False, False),
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
        self._last_path: str | None = None
        self._tmp_dir: str | None = None
        self._watched_layer = None
        self._suppress_refresh_until = 0.0
        self._custom_palette: list[str] | None = None
        self._prev_palette_index = 0
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

        head_row = QHBoxLayout()
        head_text = QVBoxLayout()
        head_text.setSpacing(0)
        title = QLabel("02viz")
        title.setObjectName("o2vizTitle")
        head_text.addWidget(title)
        tagline = QLabel("Zero2Visual · from zero to elegant visuals")
        tagline.setObjectName("o2vizTagline")
        head_text.addWidget(tagline)
        head_row.addLayout(head_text)
        head_row.addStretch(1)
        self.guide_btn = QPushButton("❔ Guide")
        self.guide_btn.setToolTip(
            "Open the full 02viz user guide — what every part does and how to "
            "get a great result (with suggestions for the current layer)")
        self.guide_btn.clicked.connect(self._open_guide)
        head_row.addWidget(self.guide_btn, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head_row)

        # the layer + scope are shared by all three surfaces (charts, on-canvas
        # diagrams, labels), so the Data card lives above the tabs
        root.addWidget(self._build_data_card())

        self.tabs = QTabWidget()
        for page, label in ((self._build_charts_tab(), "Charts"),
                            (self._build_diagrams_tab(), "Map diagrams"),
                            (self._build_labels_tab(), "Labels")):
            # pin a light page background so a dark host *stylesheet* (e.g. a
            # Night-Mapping UI theme that sets QWidget{background:dark}) can't
            # bleed through the chart area or the gaps around the cards
            page.setObjectName("o2vizTabPage")
            self.tabs.addTab(page, label)
        root.addWidget(self.tabs, 1)

        self.status = QLabel("Ready")
        self.status.setObjectName("o2vizStatus")
        root.addWidget(self.status)

        self.setWidget(container)
        self._on_layer_changed(self.layer_combo.currentLayer())
        self._sync_engine_types()
        self._sync_controls()
        self._sync_swatches()

    # ── shared Data card ──

    def _build_data_card(self) -> QFrame:
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
        return data_card

    # ── Charts tab: the visualization studio ──

    def _build_charts_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(8)

        chart_card, chart_lay = self._card("Chart")
        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        # Engine first: the engine decides which chart types are drawable, so
        # the user picks the renderer, then chooses from its supported types.
        self.engine_combo = QComboBox()
        for eng in engines():
            label = eng.label if eng.available() else f"{eng.label}  (install…)"
            self.engine_combo.addItem(label, eng.id)
        self.engine_combo.setToolTip(
            "Vendored JS engines work offline with no setup; advanced engines "
            "(matplotlib/seaborn) install on demand for publication-grade static charts")
        form.addRow("Engine", self.engine_combo)

        self.type_combo = QComboBox()
        for key, label in CHART_TYPES:
            self.type_combo.addItem(label, key)
        self.type_combo.currentIndexChanged.connect(self._sync_controls)
        form.addRow("Type", self.type_combo)

        # wire the engine→type filter only now that type_combo exists
        # (engine_combo was populated above without a connected slot, so no
        # premature fire while type_combo was still missing)
        self.engine_combo.currentIndexChanged.connect(self._sync_engine_types)

        self.theme_combo = QComboBox()
        for name in THEMES:
            self.theme_combo.addItem(name)
        self.theme_combo.setCurrentText(DEFAULT_THEME)
        self.theme_combo.currentIndexChanged.connect(self._sync_swatches)
        form.addRow("Theme", self.theme_combo)

        self.palette_combo = QComboBox()
        for name in PALETTES:
            self.palette_combo.addItem(name)
        self.palette_combo.addItem(CUSTOM_PALETTE_LABEL)
        self.palette_combo.setToolTip(
            "Series colours — overrides the theme palette in every engine. "
            "Pick 'Custom…' or click a swatch to define your own.")
        # connect after populating so the addItem loop doesn't fire the handler
        self.palette_combo.currentIndexChanged.connect(self._on_palette_changed)
        form.addRow("Colors", self.palette_combo)

        # inline, embedded swatch editor — click a swatch to recolour, +/− to
        # resize the palette; any edit switches to a custom palette. No modal.
        self._swatch_host = QWidget()
        self._swatch_row = QHBoxLayout(self._swatch_host)
        self._swatch_row.setContentsMargins(0, 0, 0, 0)
        self._swatch_row.setSpacing(4)
        form.addRow("", self._swatch_host)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("(layer name)")
        self.title_edit.setToolTip("Override the chart title; empty uses the layer name")
        form.addRow("Title", self.title_edit)

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

        self.animate_combo = self._field_combo()
        self.animate_combo.setToolTip(
            "Play the chart through this field's values — a bar-chart race, "
            "Gapminder bubbles, composition over the years. ECharts / Plotly; "
            "bar · line · area · scatter · bubble · pie.")
        form.addRow("Animate by ▶", self.animate_combo)
        self.speed_combo = QComboBox()
        for _lbl, _ms in (("Slow", 1600), ("Medium", 900), ("Fast", 450)):
            self.speed_combo.addItem(_lbl, _ms)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.setToolTip("Animation speed (time spent on each frame)")
        form.addRow("Play speed", self.speed_combo)

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
        outer.addWidget(chart_card)

        btn_row = QHBoxLayout()
        self.render_btn = QPushButton("Render chart")
        self.render_btn.setStyleSheet(_RENDER_BTN_QSS)
        self.render_btn.clicked.connect(self._render)
        btn_row.addWidget(self.render_btn, 2)
        self.suggest_btn = QPushButton("💡 Suggest")
        self.suggest_btn.setToolTip(
            "Let 02viz pick the most insightful chart for this layer's fields, "
            "configure the controls and render it")
        self.suggest_btn.clicked.connect(self._suggest_chart)
        btn_row.addWidget(self.suggest_btn, 1)
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
        self.browser_btn = QPushButton("↗")
        self.browser_btn.setToolTip(
            "Open the current chart in your system web browser "
            "(use this if the embedded panel stays blank)")
        self.browser_btn.setEnabled(False)
        self.browser_btn.setFixedWidth(34)
        self.browser_btn.clicked.connect(self._open_in_browser)
        btn_row.addWidget(self.browser_btn)
        outer.addLayout(btn_row)

        self._view_slot = QVBoxLayout()
        self._view_placeholder = QLabel(
            "Pick a layer, choose a chart type and hit Render."
        )
        self._view_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view_placeholder.setStyleSheet("color: #8d99ae; padding: 22px;")
        self._view_slot.addWidget(self._view_placeholder)
        outer.addLayout(self._view_slot, 1)
        return tab

    # ── Map diagrams tab: native QGIS diagrams on every feature ──

    def _build_diagrams_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(8)
        card, c = self._card("Map diagrams — on canvas")
        c.addWidget(QLabel(
            "Draw a diagram on every feature, on the map canvas, "
            "coloured with the studio palette."))
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Type"))
        self.diag_type_combo = QComboBox()
        for key in diagrams.DIAGRAM_TYPES:
            self.diag_type_combo.addItem(diagrams.DIAGRAM_LABELS[key], key)
        trow.addWidget(self.diag_type_combo, 1)
        c.addLayout(trow)
        c.addWidget(QLabel("Fields (numeric — slices / bars):"))
        self.diag_field_list = QListWidget()
        self.diag_field_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.diag_field_list.setMaximumHeight(150)
        c.addWidget(self.diag_field_list)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Size (mm)"))
        self.diag_size_spin = QDoubleSpinBox()
        self.diag_size_spin.setRange(3.0, 60.0)
        self.diag_size_spin.setValue(14.0)
        srow.addWidget(self.diag_size_spin)
        srow.addStretch(1)
        c.addLayout(srow)

        nrow = QHBoxLayout()
        nrow.addWidget(QLabel("Normalize"))
        self.diag_norm_combo = QComboBox()
        for key in expressions.NORMALIZE_MODES:
            self.diag_norm_combo.addItem(expressions.NORMALIZE_LABELS[key], key)
        self.diag_norm_combo.setToolTip(
            "Make differently-scaled fields comparable on every feature. "
            "Raw values let a big-number field swamp the rest; Min–max (0–1) is "
            "the safe default, Z-score standardises, Log compresses heavy tails.")
        self.diag_norm_combo.currentIndexChanged.connect(self._sync_diag_hint)
        self.diag_type_combo.currentIndexChanged.connect(self._sync_diag_hint)
        nrow.addWidget(self.diag_norm_combo, 1)
        c.addLayout(nrow)
        self.diag_hint = QLabel("")
        self.diag_hint.setWordWrap(True)
        self.diag_hint.setStyleSheet("color: #6b7a82; font-size: 11px;")
        c.addWidget(self.diag_hint)

        brow = QHBoxLayout()
        diag_apply = QPushButton("Apply to layer")
        diag_apply.setStyleSheet(_RENDER_BTN_QSS)
        diag_apply.clicked.connect(self._apply_diagram)
        brow.addWidget(diag_apply)
        diag_clear = QPushButton("Clear")
        diag_clear.setToolTip("Remove diagrams from this layer")
        diag_clear.clicked.connect(self._clear_diagram)
        brow.addWidget(diag_clear)
        brow.addStretch(1)
        c.addLayout(brow)
        outer.addWidget(card)
        outer.addStretch(1)
        return tab

    # ── Labels tab: format, round & multi-line feature labels ──

    def _build_labels_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(8)
        card, c = self._card("Labels — format, round & multi-line")
        c.addWidget(QLabel(
            "Turn fields into well-placed labels — round numbers, stack a second "
            "line, add units, or write your own expression."))
        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        self.label_field_combo = self._field_combo()
        self.label_field_combo.fieldChanged.connect(self._sync_label_preview)
        form.addRow("Label field", self.label_field_combo)

        self.label_field2_combo = self._field_combo()
        self.label_field2_combo.setToolTip(
            "Optional — shown on a second line below the first")
        self.label_field2_combo.fieldChanged.connect(self._sync_label_preview)
        form.addRow("Second line", self.label_field2_combo)

        self.label_decimals_spin = QSpinBox()
        self.label_decimals_spin.setRange(-1, 6)
        self.label_decimals_spin.setValue(-1)
        self.label_decimals_spin.setSpecialValueText("off")
        self.label_decimals_spin.setToolTip(
            "Round numeric labels to this many decimals (off = leave as is)")
        self.label_decimals_spin.valueChanged.connect(self._sync_label_preview)
        form.addRow("Decimals", self.label_decimals_spin)

        self.label_thousands_check = QCheckBox("Thousands separator (1,234)")
        self.label_thousands_check.toggled.connect(self._sync_label_preview)
        form.addRow("", self.label_thousands_check)

        prow = QHBoxLayout()
        self.label_prefix_edit = QLineEdit()
        self.label_prefix_edit.setPlaceholderText("prefix")
        self.label_prefix_edit.setMaximumWidth(86)
        self.label_prefix_edit.textChanged.connect(self._sync_label_preview)
        prow.addWidget(self.label_prefix_edit)
        prow.addWidget(QLabel("…value…"))
        self.label_suffix_edit = QLineEdit()
        self.label_suffix_edit.setPlaceholderText("suffix")
        self.label_suffix_edit.setMaximumWidth(86)
        self.label_suffix_edit.textChanged.connect(self._sync_label_preview)
        prow.addWidget(self.label_suffix_edit)
        prow.addStretch(1)
        form.addRow("Prefix / Suffix", prow)

        self.label_case_combo = QComboBox()
        for key in expressions.LABEL_CASES:
            self.label_case_combo.addItem(expressions.LABEL_CASE_LABELS[key], key)
        self.label_case_combo.currentIndexChanged.connect(self._sync_label_preview)
        form.addRow("Case", self.label_case_combo)

        self.label_wrap_spin = QSpinBox()
        self.label_wrap_spin.setRange(0, 80)
        self.label_wrap_spin.setValue(0)
        self.label_wrap_spin.setSpecialValueText("off")
        self.label_wrap_spin.setToolTip(
            "Wrap long labels at this many characters (off = no wrap)")
        self.label_wrap_spin.valueChanged.connect(self._sync_label_preview)
        form.addRow("Wrap at", self.label_wrap_spin)

        self.label_preset_combo = QComboBox()
        for key, lbl in labels.PRESETS:
            self.label_preset_combo.addItem(lbl, key)
        form.addRow("Style", self.label_preset_combo)

        self.label_size_spin = QDoubleSpinBox()
        self.label_size_spin.setRange(5.0, 40.0)
        self.label_size_spin.setValue(9.0)
        form.addRow("Size (pt)", self.label_size_spin)

        self.label_expr_edit = QLineEdit()
        self.label_expr_edit.setPlaceholderText(
            "advanced QGIS expression — overrides the controls above")
        self.label_expr_edit.setToolTip(
            "Type any QGIS expression, e.g. "
            "concat(\"name\", char(10), round(\"pop\", 0)). "
            "When filled it overrides the formatting controls above.")
        self.label_expr_edit.textChanged.connect(self._sync_label_preview)
        form.addRow("Expression", self.label_expr_edit)
        c.addLayout(form)

        self.label_preview = QLabel("")
        self.label_preview.setWordWrap(True)
        self.label_preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label_preview.setToolTip("The exact label expression being applied"
                                      " — and a sample from the first feature")
        self.label_preview.setStyleSheet(
            "color:#207168; background:#f0f4f6; border:1px solid #e0e7ea;"
            " border-radius:6px; padding:5px 8px;"
            " font-family:Consolas,monospace; font-size:11px;")
        c.addWidget(self.label_preview)

        brow = QHBoxLayout()
        lbl_apply = QPushButton("Apply to layer")
        lbl_apply.setStyleSheet(_RENDER_BTN_QSS)
        lbl_apply.clicked.connect(self._apply_labels)
        brow.addWidget(lbl_apply)
        lbl_clear = QPushButton("Clear")
        lbl_clear.setToolTip("Remove labels from this layer")
        lbl_clear.clicked.connect(self._clear_labels)
        brow.addWidget(lbl_clear)
        brow.addStretch(1)
        c.addLayout(brow)
        outer.addWidget(card)
        outer.addStretch(1)
        return tab

    # ───────────────────────── wiring ─────────────────────────

    def _on_layer_changed(self, layer) -> None:
        for combo in (self.x_combo, self.y_combo, self.group_combo,
                      self.value_combo, self.animate_combo,
                      self.label_field_combo, self.label_field2_combo):
            combo.setLayer(layer)
        self._refresh_diagram_fields(layer)
        self._sync_diag_hint()
        self._sync_label_preview()
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
            # nudge the chart to re-measure now that the view is laid out —
            # the engine bodies also self-fit, this covers the first paint
            run_js(self._view_kind, self._view,
                   "window.dispatchEvent(new Event('resize'));")
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

    def _sync_engine_types(self, *_args) -> None:
        """Grey out chart types the selected engine cannot draw
        (e.g. Vega-Lite has no treemap/sunburst grammar)."""
        eng = engines()[max(0, self.engine_combo.currentIndex())]
        model = self.type_combo.model()
        for i in range(self.type_combo.count()):
            model.item(i).setEnabled(self.type_combo.itemData(i) in eng.supports)
        if self.type_combo.currentData() not in eng.supports:
            for i in range(self.type_combo.count()):
                if self.type_combo.itemData(i) in eng.supports:
                    self.type_combo.setCurrentIndex(i)
                    break
        self._sync_animate()

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
        self._sync_animate()

    def _sync_animate(self, *_args) -> None:
        """The play axis only lights up when the chosen engine can animate the
        chosen chart type (ECharts / Plotly · bar·line·area·scatter·bubble·pie)."""
        if not hasattr(self, "animate_combo"):
            return
        eng = engines()[max(0, self.engine_combo.currentIndex())]
        on = self.type_combo.currentData() in eng.animates
        self.animate_combo.setEnabled(on)
        self.speed_combo.setEnabled(on)

    # ── Map diagrams tab handlers ──

    def _refresh_diagram_fields(self, layer) -> None:
        if not hasattr(self, "diag_field_list"):
            return
        self.diag_field_list.clear()
        if layer is None:
            return
        for name in diagrams.numeric_field_names(layer):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.diag_field_list.addItem(item)

    def _checked_diagram_fields(self) -> list[str]:
        return [self.diag_field_list.item(i).text()
                for i in range(self.diag_field_list.count())
                if self.diag_field_list.item(i).checkState() == Qt.CheckState.Checked]

    def _apply_diagram(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is None:
            self.set_status("Pick a layer first")
            return
        fields = self._checked_diagram_fields()
        if not fields:
            self.set_status("Tick at least one numeric field for the diagram")
            return
        kind = self.diag_type_combo.currentData()
        normalize = self.diag_norm_combo.currentData()
        field_stats: dict = {}
        if normalize != "none":
            try:
                cols = datasource.columns(layer, fields,
                                          self.selected_only.isChecked())
            except ValueError as exc:
                self.set_status(str(exc))
                return
            for name in fields:
                st = stats.field_numeric_stats(cols[name])
                if st:
                    field_stats[name] = st
        ok = diagrams.apply_diagram(
            layer, kind=kind, fields=fields,
            colors=list(self._current_theme()["palette"]),
            size_mm=self.diag_size_spin.value(),
            normalize=normalize, stats=field_stats)
        if not ok:
            self.set_status("Could not apply the diagram (no geometry?)")
            return
        self._refresh_canvas(layer)
        norm_txt = ("" if normalize == "none"
                    else ", " + expressions.NORMALIZE_LABELS[normalize].lower())
        self.set_status(
            f"Applied {diagrams.DIAGRAM_LABELS[kind].lower()} diagram "
            f"({len(fields)} field{'s' if len(fields) != 1 else ''}{norm_txt}) "
            f"on the canvas")

    def _sync_diag_hint(self, *_args) -> None:
        if not hasattr(self, "diag_hint"):
            return
        kind = self.diag_type_combo.currentData()
        mode = self.diag_norm_combo.currentData()
        msg = {
            "none": "Raw values — fine when fields share a scale; otherwise a "
                    "big-number field dominates the others.",
            "minmax": "Each field scaled to 0–1 — the safe choice for comparing "
                      "pies and bars across fields.",
            "zscore": "Standardised to mean 0 — great for bars; values can be "
                      "negative.",
            "log": "Log-compressed — tames heavy tails or a few dominant features.",
        }.get(mode, "")
        if mode == "zscore" and kind in ("pie", "stacked"):
            msg = ("⚠ Z-score can be negative, which a pie / stacked bar can't "
                   "draw — use Min–max or Log for this diagram type.")
        self.diag_hint.setText(msg)

    def _clear_diagram(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is None:
            return
        diagrams.clear_diagram(layer)
        self._refresh_canvas(layer)
        self.set_status("Diagrams removed from this layer")

    # ── Labels tab handlers ──

    def _build_label_expression(self) -> str:
        """The label expression in effect: the advanced box if filled, else
        assembled from the format controls (pure — see core.expressions)."""
        layer = self.layer_combo.currentLayer()
        numeric = (set(diagrams.numeric_field_names(layer))
                   if layer is not None else None)
        return expressions.label_expression(
            [self.label_field_combo.currentField(),
             self.label_field2_combo.currentField()],
            decimals=self.label_decimals_spin.value(),
            thousands=self.label_thousands_check.isChecked(),
            prefix=self.label_prefix_edit.text(),
            suffix=self.label_suffix_edit.text(),
            case=self.label_case_combo.currentData(),
            wrap=self.label_wrap_spin.value(),
            multiline=True, numeric_fields=numeric,
            custom=self.label_expr_edit.text())

    def _sample_label(self, expr: str) -> str:
        """Best-effort evaluation of ``expr`` on the first feature, for the
        live preview. Returns '' (or a short parser note) on any problem."""
        layer = self.layer_combo.currentLayer()
        if layer is None or not expr:
            return ""
        try:
            from qgis.core import (
                QgsExpression, QgsExpressionContext, QgsExpressionContextUtils,
            )
            parsed = QgsExpression(expr)
            if parsed.hasParserError():
                return "⚠ " + parsed.parserErrorString().strip()
            feat = next(layer.getFeatures(), None)
            if feat is None:
                return ""
            ctx = QgsExpressionContext()
            ctx.appendScopes(
                QgsExpressionContextUtils.globalProjectLayerScopes(layer))
            ctx.setFeature(feat)
            val = parsed.evaluate(ctx)
            if parsed.hasEvalError():
                return ""
            text = "" if val is None else str(val)
            return (text[:70] + "…") if len(text) > 70 else text
        except Exception:
            return ""

    def _sync_label_preview(self, *_args) -> None:
        if not hasattr(self, "label_preview"):
            return
        # advanced box overrides → grey out the format controls so it's clear
        custom = bool(self.label_expr_edit.text().strip())
        for w in (self.label_field_combo, self.label_field2_combo,
                  self.label_decimals_spin, self.label_thousands_check,
                  self.label_prefix_edit, self.label_suffix_edit,
                  self.label_case_combo, self.label_wrap_spin):
            w.setEnabled(not custom)
        expr = self._build_label_expression()
        sample = self._sample_label(expr)
        self.label_preview.setText(expr + (f"\n→  {sample}" if sample else ""))

    def _apply_labels(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is None:
            self.set_status("Pick a layer first")
            return
        expr = self._build_label_expression()
        if expr in ("", "''"):
            self.set_status("Pick a field to label, or type an expression")
            return
        try:  # don't let a typo silently produce no labels
            from qgis.core import QgsExpression
            parsed = QgsExpression(expr)
            if parsed.hasParserError():
                self.set_status("Expression error: "
                                + parsed.parserErrorString().strip())
                return
        except Exception:
            pass
        ok = labels.apply_labels(
            layer, expression=expr, preset=self.label_preset_combo.currentData(),
            color=self._current_theme()["text"], size=self.label_size_spin.value())
        if not ok:
            self.set_status("Could not apply labels")
            return
        self._refresh_canvas(layer)
        self.set_status("Labelled features · "
                        + (expr[:70] + ("…" if len(expr) > 70 else "")))

    def _clear_labels(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is None:
            return
        labels.clear_labels(layer)
        self._refresh_canvas(layer)
        self.set_status("Labels removed from this layer")

    def _refresh_canvas(self, layer) -> None:
        try:
            self.iface.layerTreeView().refreshLayerSymbology(layer.id())
        except Exception:
            pass
        try:
            self.iface.mapCanvas().refreshAllLayers()
        except Exception:
            pass

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
        eng = engines()[max(0, self.engine_combo.currentIndex())]
        x = self.x_combo.currentField()
        y = self.y_combo.currentField()
        group = self.group_combo.currentField() if self.group_combo.isEnabled() else ""
        value = self.value_combo.currentField() if self.value_combo.isEnabled() else ""
        animate = (self.animate_combo.currentField()
                   if self.animate_combo.isEnabled() else "")
        agg = self.agg_combo.currentText()
        sel = self.selected_only.isChecked()

        fields = [f for f in {x, y, group, value, animate} if f]
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

        title = self.title_edit.text().strip() or layer.name()
        spec = {"type": kind, "title": title, "x_label": x, "y_label": y,
                "stacked": self.stacked_check.isChecked(),
                "theme": self._current_theme()}

        builder = getattr(self, f"_spec_{kind}", None)
        data = builder(spec, cols, fids, x=x, y=y, group=group, value=value, agg=agg)
        if data is None:
            return None
        spec["data"] = data
        if animate and kind in eng.animates:
            frames = self._build_frames(
                spec, cols, fids, kind=kind, x=x, y=y, group=group,
                value=value, agg=agg, frame_field=animate)
            if frames is None:
                return None  # _build_frames sets the status
            spec["frames"] = frames
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

    def _group_buckets(self, source: list | None, values: list, fallback: str):
        """Bucket ``values`` by ``source`` keys (first-appearance order);
        a single bucket named ``fallback`` when there is no grouping field."""
        if source is None:
            return [fallback], {fallback: values}
        buckets: dict[str, list] = {}
        order: list[str] = []
        for i, raw in enumerate(source):
            key = transform._key(raw)
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(values[i])
        return order, buckets

    def _spec_box(self, spec, cols, fids, *, x, y, group, value, agg):
        if not y:
            self.set_status("Box plot needs a Y field (numeric)")
            return None
        source = cols[group] if group else (cols[x] if x else None)
        order, buckets = self._group_buckets(source, cols[y], y)
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

    def _spec_errorband(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x or not y:
            self.set_status("Mean ± σ needs an X category and a numeric Y field")
            return None
        cats, series = transform.band_rows(cols[x], cols[y],
                                           cols[group] if group else None, fids)
        if not series:
            self.set_status(f"No numeric values in '{y}'")
            return None
        spec["y_label"] = f"mean({y}) ± 1σ"
        return {"categories": cats, "series": series}

    _spec_errorbar = _spec_errorband

    def _spec_density(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x:
            self.set_status("Density needs a numeric X field")
            return None
        order, buckets = self._group_buckets(cols[group] if group else None,
                                             cols[x], x)
        series = []
        for key in order:
            pts = stats.kde_points(buckets[key])
            if pts:
                series.append({"name": key, "points": pts})
        if not series:
            self.set_status(f"Need at least 2 distinct numeric values in '{x}'")
            return None
        spec["y_label"] = "density"
        return {"series": series}

    def _spec_violin(self, spec, cols, fids, *, x, y, group, value, agg):
        if not y:
            self.set_status("Violin needs a numeric Y field")
            return None
        source = cols[group] if group else (cols[x] if x else None)
        order, buckets = self._group_buckets(source, cols[y], y)
        groups, polygons, medians = transform.violin_rows(order, buckets)
        if not groups:
            self.set_status(
                f"Violin needs ≥ 2 distinct numeric '{y}' values per group")
            return None
        return {"groups": groups, "polygons": polygons, "medians": medians}

    def _spec_radar(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x:
            self.set_status("Radar needs an X / Category field for the axes")
            return None
        how = self._agg_or(agg, "mean")
        if how != "count" and not y:
            self.set_status(f"Aggregation '{how}' needs a Y field")
            return None
        spec["y_label"] = f"{how}({y})" if how != "count" else "count"
        if group:
            axes, raw = transform.pivot_rows(cols[x], cols[group],
                                             cols.get(y, []), fids, how)
            series = [{"name": s["name"], "values": s["values"]} for s in raw]
        else:
            axes, vals, _ids = transform.group_rows(cols[x], cols.get(y, []),
                                                    fids, how)
            series = [{"name": spec["y_label"], "values": vals}]
        if len(axes) < 3:
            self.set_status("Radar needs at least 3 categories on X")
            return None
        return {"axes": axes, "series": series,
                "maxes": transform.radar_axis_maxes(series)}

    def _spec_pareto(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x:
            self.set_status("Pareto needs an X / Category field")
            return None
        how = self._agg_or(agg, "count")
        if how != "count" and not y:
            self.set_status(f"Aggregation '{how}' needs a Y field")
            return None
        spec["y_label"] = f"{how}({y})" if how != "count" else "count"
        cats, vals, ids = transform.group_rows(cols[x], cols.get(y, []), fids, how)
        cats, vals, ids = transform.topn_collapse(cats, vals, ids,
                                                  self.topn_spin.value())
        cats, vals, cum, ids = transform.pareto_rows(cats, vals, ids)
        return {"categories": cats, "values": vals, "cum": cum, "ids": ids}

    # ───────────────────────── animation (play axis) ─────────────────────────

    def _build_frames(self, spec, cols, fids, *, kind, x, y, group, value, agg,
                      frame_field):
        """Assemble the ``frames`` block for an animated chart. Validates the
        field roles, then delegates the slicing/alignment to the pure
        :func:`transform.build_frames` (so it stays testable headless)."""
        if kind in ("bar", "line", "area", "pie"):
            how = self._agg_or(agg, "count")
            if how != "count" and not y:
                self.set_status(f"Aggregation '{how}' needs a Y field")
                return None
            spec["y_label"] = f"{how}({y})" if how != "count" else "count"
            single = spec["y_label"]
        elif kind in ("scatter", "bubble"):
            if not x or not y:
                self.set_status("This chart needs numeric X and Y fields")
                return None
            if kind == "bubble" and not value:
                self.set_status("Bubble chart needs a Value / Size field")
                return None
            how, single = "count", (spec.get("y_label") or "points")
        else:
            return None

        built = transform.build_frames(
            kind, cols, fids, cols.get(frame_field, []),
            x=x, y=y, group=group, value=value, how=how, single_name=single)
        if built is None:
            self.set_status("Animate-by needs ≥ 2 frames with chartable data")
            return None
        labels, datas, union, bounds = built
        spec["data"] = datas[0]
        return {"field": frame_field, "labels": labels, "datas": datas,
                "categories": union, "bounds": bounds,
                "interval": self.speed_combo.currentData() or 900}

    # ───────────────────────── render / explore / export ─────────────────────────

    # ───────────────────────── colours (embedded swatch editor) ─────────────────────────

    def _resolve_palette(self) -> list[str]:
        """The colour list in effect: custom swatches, a chosen built-in
        palette, or the active theme's palette."""
        name = self.palette_combo.currentText()
        if name == CUSTOM_PALETTE_LABEL and self._custom_palette:
            return list(self._custom_palette)
        pal = PALETTES.get(name)
        if pal:
            return list(pal)
        theme = THEMES.get(self.theme_combo.currentText(), THEMES[DEFAULT_THEME])
        return list(theme["palette"])

    def _on_palette_changed(self, idx: int) -> None:
        # picking 'Custom…' with nothing defined yet seeds from what was showing
        if (self.palette_combo.itemText(idx) == CUSTOM_PALETTE_LABEL
                and not self._custom_palette):
            prev = self.palette_combo.itemText(self._prev_palette_index)
            seed = PALETTES.get(prev) or THEMES.get(
                self.theme_combo.currentText(), THEMES[DEFAULT_THEME])["palette"]
            self._custom_palette = list(seed)
        self._prev_palette_index = self.palette_combo.currentIndex()
        self._sync_swatches()

    def _enter_custom(self, colors: list[str]) -> None:
        """Adopt ``colors`` as the custom palette and switch the combo to it."""
        self._custom_palette = list(colors)
        idx = self.palette_combo.findText(CUSTOM_PALETTE_LABEL)
        self.palette_combo.blockSignals(True)
        self.palette_combo.setCurrentIndex(idx)
        self.palette_combo.blockSignals(False)
        self._prev_palette_index = idx
        self._sync_swatches()

    def _sync_swatches(self, *_args) -> None:
        if not hasattr(self, "_swatch_row"):
            return
        while self._swatch_row.count():
            item = self._swatch_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        palette = self._resolve_palette()
        for i, color in enumerate(palette):
            sw = QPushButton()
            sw.setFixedSize(20, 20)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setToolTip(f"{color} — click to edit")
            sw.setStyleSheet(
                f"QPushButton {{ background: {color}; border: 1px solid #00000033;"
                f" border-radius: 4px; }}"
                f"QPushButton:hover {{ border: 2px solid #16323f; }}")
            sw.clicked.connect(lambda _=False, idx=i: self._edit_swatch(idx))
            self._swatch_row.addWidget(sw)
        # padding:0 so the glyph fits the 20×20 square (the generic QPushButton
        # rule's padding would otherwise clip a single +/− character)
        mini_qss = (
            "QPushButton { background: #eef1f4; color: #1f333d;"
            " border: 1px solid #cbd3da; border-radius: 4px; padding: 0;"
            " font-weight: 700; }"
            "QPushButton:hover { background: #e4e9ed; }"
            "QPushButton:disabled { color: #b9c2c9; }")
        add = QPushButton("+")
        add.setFixedSize(20, 20)
        add.setStyleSheet(mini_qss)
        add.setToolTip("Add a colour")
        add.clicked.connect(self._add_swatch)
        self._swatch_row.addWidget(add)
        rem = QPushButton("−")
        rem.setFixedSize(20, 20)
        rem.setStyleSheet(mini_qss)
        rem.setToolTip("Remove the last colour")
        rem.setEnabled(len(palette) > 1)
        rem.clicked.connect(self._remove_swatch)
        self._swatch_row.addWidget(rem)
        self._swatch_row.addStretch(1)

    def _edit_swatch(self, i: int) -> None:
        base = self._resolve_palette()
        if i >= len(base):
            return
        chosen = QColorDialog.getColor(QColor(base[i]), self, "Pick a colour")
        if chosen.isValid():
            base[i] = chosen.name()
            self._enter_custom(base)
            self.set_status("Custom palette updated")

    def _add_swatch(self) -> None:
        base = self._resolve_palette()
        if len(base) >= 16:
            return
        chosen = QColorDialog.getColor(QColor("#2a8f85"), self, "Add a colour")
        if chosen.isValid():
            base.append(chosen.name())
            self._enter_custom(base)

    def _remove_swatch(self) -> None:
        base = self._resolve_palette()
        if len(base) > 1:
            base.pop()
            self._enter_custom(base)

    def _current_theme(self) -> dict:
        theme = THEMES.get(self.theme_combo.currentText(), THEMES[DEFAULT_THEME])
        return dict(theme, palette=self._resolve_palette())

    def _ensure_view(self) -> None:
        """Create the embedded web view once, recording which backend the QGIS
        build ships (webengine / webkit / browser). Called before a render so
        the dock knows the backend in time to adapt the engine choice."""
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

    def _show_html(self, html: str, status: str, embed_html: str | None = None) -> None:
        """Show a chart. ``html`` is the real chart — always what Export and the
        ↗ browser button use. ``embed_html``, when given, is loaded into the
        panel instead (e.g. the legacy-WebKit explainer for an engine the
        embedded view can't run), without losing the real chart."""
        if self._tmp_dir is None:
            self._tmp_dir = tempfile.mkdtemp(prefix="o2viz_")
        stamp = int(time.time() * 1000)
        path = os.path.join(self._tmp_dir, f"chart_{stamp}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        self._last_html = html
        self._last_path = path

        self._ensure_view()
        if embed_html is not None:
            load_path = os.path.join(self._tmp_dir, f"embed_{stamp}.html")
            with open(load_path, "w", encoding="utf-8") as f:
                f.write(embed_html)
        else:
            load_path = path
        self.bridge.bind(self.layer_combo.currentLayer()
                         if self.link_check.isChecked() else None)
        embedded = show_html_file(self._view_kind, self._view, load_path)
        self.export_btn.setEnabled(True)
        self.browser_btn.setEnabled(True)
        if embedded:
            where = f" · {self._view_kind}"
        else:
            where = " (no embedded web view in this QGIS build — opened in your browser)"
        self.set_status(status + where)

    def _open_in_browser(self) -> None:
        """Escape hatch: show the last chart in the system browser. Always
        works, even when the embedded QWebEngine view paints blank."""
        if not self._last_path or not os.path.exists(self._last_path):
            if not self._last_html:
                return
            self._show_html(self._last_html, "Reopened")  # rebuilds the temp file
        import webbrowser
        webbrowser.open("file:///" + self._last_path.replace("\\", "/"))
        self.set_status("Opened the current chart in your browser")

    def _render(self) -> None:
        engine = engines()[max(0, self.engine_combo.currentIndex())]
        if not self._ensure_engine_available(engine):
            return
        try:
            spec = self._build_spec()
            if spec is None:
                return
            if spec["type"] not in engine.supports:
                self.set_status(f"{engine.label} cannot draw {spec['type']} charts")
                return
            html = engine.build_html(spec)
        except Exception as exc:
            self.set_status(f"Chart failed: {exc}")
            return
        self._ensure_view()
        if self._view_kind == "webkit" and not engine.webkit_ok:
            # legacy QtWebKit (no QtWebEngine in this QGIS) can't run Plotly's /
            # Vega's modern JS — they parse-fail and the panel stays blank. Show
            # an explainer there, but keep the real chart for export / ↗ browser.
            self._show_html(
                html,
                f"{engine.label}: open in your browser ↗ — the embedded WebKit "
                f"view can't run it (try the ECharts engine for an embedded chart)",
                embed_html=webkit_fallback_page(engine.label, spec.get("type", "")))
        else:
            self._show_html(html, f"Rendered {spec['type']} · {engine.label}")

    # ───────────────────────── advanced engine availability ─────────────────────────

    def _refresh_engine_labels(self) -> None:
        for i in range(self.engine_combo.count()):
            eng = engines()[i]
            label = eng.label if eng.available() else f"{eng.label}  (install…)"
            self.engine_combo.setItemText(i, label)

    def _ensure_engine_available(self, engine) -> bool:
        """If an optional engine's libraries are missing, offer to install them
        (explicit click only) into the QGIS Python. Returns True if usable."""
        if engine.available():
            return True
        pkgs = requirements.ENGINE_PIP_REQUIREMENTS.get(engine.id, [])
        missing = requirements.missing_packages(pkgs)
        if not missing:
            return True
        cmd = " ".join(requirements.install_command(missing))
        resp = QMessageBox.question(
            self, "Install advanced engine",
            f"<b>{engine.label}</b> needs: {', '.join(missing)}.<br><br>"
            f"Install now into the QGIS Python (user site-packages)?<br>"
            f"<code>{cmd}</code>",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if resp != QMessageBox.StandardButton.Yes:
            self.set_status(f"{engine.label} needs {', '.join(missing)}")
            return False
        self.set_status(f"Installing {', '.join(missing)} — this can take a minute…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            ok, log = requirements.run_pip_install(missing)
        finally:
            QApplication.restoreOverrideCursor()
        if ok and engine.available():
            self._refresh_engine_labels()
            self.set_status(f"Installed {', '.join(missing)} — ready")
            return True
        QMessageBox.warning(self, "Install failed",
                            (log or "pip failed")[-1600:])
        self.set_status("Install failed — see the dialog")
        return False

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

    # ───────────────────────── smart assistant ─────────────────────────

    def _suggest_chart(self) -> None:
        """Offline assistant: pick the best chart for this layer, configure the
        controls and render it."""
        layer = self.layer_combo.currentLayer()
        if layer is None:
            self.set_status("Pick a layer first")
            return
        try:
            names = [f.name() for f in layer.fields()]
            cols, fids = datasource.columns_with_ids(
                layer, names, self.selected_only.isChecked())
        except Exception as exc:
            self.set_status(f"Suggest failed: {exc}")
            return
        sug = assistant.suggest_chart(cols, fids)
        if not sug:
            self.set_status("No clear chart suggestion — try ✨ Explore for an overview")
            return
        self._apply_chart_suggestion(sug)
        self.set_status("💡 " + sug["why"])
        self._render()

    def _apply_chart_suggestion(self, sug: dict) -> None:
        kind = sug["type"]
        eng = engines()[max(0, self.engine_combo.currentIndex())]
        if kind not in eng.supports:  # switch to an engine that can draw it
            for i, e in enumerate(engines()):
                if kind in e.supports:
                    self.engine_combo.setCurrentIndex(i)
                    break
        for i in range(self.type_combo.count()):
            if self.type_combo.itemData(i) == kind:
                self.type_combo.setCurrentIndex(i)
                break
        self._sync_controls()
        self.x_combo.setField(sug.get("x") or "")
        self.y_combo.setField(sug.get("y") or "")
        self.group_combo.setField(sug.get("group") or "")
        self.value_combo.setField(sug.get("value") or "")
        agg_i = self.agg_combo.findText(sug.get("agg") or "none")
        if agg_i >= 0:
            self.agg_combo.setCurrentIndex(agg_i)
        self.trend_check.setChecked(bool(sug.get("trend")))

    def _open_guide(self) -> None:
        """Show the full user guide, with suggestions for the active layer."""
        layer = self.layer_combo.currentLayer()
        layer_name = layer.name() if layer is not None else ""
        suggestions = None
        if layer is not None:
            try:
                names = [f.name() for f in layer.fields()]
                cols, fids = datasource.columns_with_ids(
                    layer, names, self.selected_only.isChecked())
                suggestions = assistant.suggestions(
                    cols, has_geometry=diagrams.layer_has_geometry(layer), fids=fids)
            except Exception:
                suggestions = None
        html = build_guide_html(suggestions=suggestions, layer_name=layer_name)
        self.tabs.setCurrentIndex(0)  # the embedded view lives on the Charts tab
        self._show_html(html, "Opened the 02viz user guide")

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
