# -*- coding: utf-8 -*-
"""02viz studio dock — charts, map diagrams and labels under one roof.

A shared Data card (layer / selected-only / external table) above three tabs:
**Charts** (type/fields/style first, engine and the rest folded under
**Advanced** → embedded viewer with a chart→map selection bridge; spec
assembly in ``_build_spec``), **Map diagrams** (native on-canvas diagrams with
optional normalisation) and **Labels** (expression-driven, formatted,
multi-line labels). The primary action of the open tab (Render chart +
Export menu, or Apply / Clear) and the status line are pinned under the
scrolling panel, so they stay in reach at any dock height. A header **Guide**
button shows the offline user guide and **Suggest** asks the offline
assistant for the most suitable chart. Rendering goes through the engine
registry, so engines never touch Qt; the pure logic lives in ``core``.
"""
from __future__ import annotations

import contextlib
import html as html_lib
import json
import os
import re
import shutil
import tempfile
import time
from contextlib import suppress

from qgis.PyQt.QtCore import QEvent, QObject, Qt, QPoint, QRect, QTimer, QSettings, QSize
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
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
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMenu,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication, QgsFieldProxyModel, QgsProject, QgsVectorLayer
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox

from ..core import (
    assistant, datasource, diagrams, expressions, labels,
    overlays, presets, profile as profiler, requirements, stats, transform,
)
from ..core.export_utils import (
    atomic_write_text,
    ensure_extension,
    human_size,
)
from ..engines import engines
from ..engines.base import DEFAULT_THEME, HORIZONTAL_TYPES, PALETTES, THEMES
from ..engines.dashboard import build_dashboard
from ..engines.guide import build_guide_html
from . import exports
from .bridge import SelectionBridge
from .webview import (
    attach_title_listener, create_chart_view, eval_js, run_js, show_html_file,
    show_html_text,
)

# above this many selected features, skip the cross-filter highlight (the
# injected id list would dwarf any visual benefit)
MAX_HIGHLIGHT_IDS = 20000

# sentinel entry in the Colors combo that opens the custom palette editor
CUSTOM_PALETTE_LABEL = "Custom…"

PRESET_SETTINGS_KEY = "zero2viz/chart_presets"
# the last chart setup, restored when the panel opens again (also after a
# QGIS restart): the preset fields plus the layer id and panel state
LAST_SETUP_KEY = "zero2viz/last_setup"
PNG_SIZE_KEY = "zero2viz/png_size"
# one rendered page per dock, rewritten in place and removed on unload
CHART_FILE_NAME = "chart.html"
# edits on the charted layer arrive in bursts (one signal per feature/field);
# redraw once they settle
STALE_REDRAW_MS = 600

# primary action colour: white text on it is 5.1:1 (WCAG AA needs 4.5:1;
# the old #2a8f85 was 3.9:1)
_ACCENT = "#237a72"
_ACCENT_HOVER = "#1d6a63"
# placeholder / hint text: 5.3:1 on white (the old #8d99ae was 2.9:1)
_MUTED_TEXT = "#5f6e76"

# 💡 Suggest: how many numeric fields it will ever pull into Python for one
# click, independent of core.assistant's O(fields^2) scan cap — a wide
# grid/zonal-stats layer's raw field*row pull is itself heavy enough to
# strain memory before any analysis even starts.
_SUGGEST_FIELD_CAP = 60
_SUGGEST_FULL_FIELD_CAP = 300  # after the user explicitly asks for a full scan
_FACET_CAP = 12  # small-multiple panels; larger groups kept, the rest reported

# The studio has its own light visual identity (light root, white cards). On
# QGIS 3 (Qt5) the host palette is light too, so unstyled child widgets looked
# fine by accident. On QGIS 4 (Qt6) the host palette is often dark: every
# colour we DON'T pin is then inherited from it, so the combo popups paint
# near-black and the field labels/checkboxes turn into light-on-white ghosts
# (the "black dropdown + unreadable label" bug). The remedy is to pin every text
# and input colour here, so the panel reads identically under any host theme.
_DOCK_QSS = """
QWidget#o2vizRoot, QWidget#o2vizContent { background: #fbfbfd; }
QWidget#o2vizTabPage { background: #ffffff; }
QWidget#o2vizActionBar { background: #fbfbfd; }
QToolButton#o2vizFold { border: none; background: transparent; color: #16323f;
                        font-weight: 600; padding: 4px 2px; }
QToolButton#o2vizFold:hover { color: #237a72; }
QToolButton#o2vizExportMenu {
    background: #eef1f4; color: #1f333d; border: 1px solid #cbd3da;
    border-radius: 6px; padding: 6px 10px; }
QToolButton#o2vizExportMenu:hover { background: #e4e9ed; }
QToolButton#o2vizExportMenu:disabled { background: #f2f4f6; color: #9aa6ae;
                                       border-color: #e2e6ea; }
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
/* font-weight is fixed at 600 for BOTH states on purpose: QTabBar sizes each
   tab once from its normal-state text metrics, so making only :selected bold
   widens that tab's text past the box it was already sized for — Qt does not
   re-lay-out the tab on a pseudo-state change, so the wider glyphs got
   clipped/overlapped ("kendi metin bloğuna sığmıyor"). Keeping the weight
   constant and varying only colour/background avoids the mismatch entirely. */
/* each tab sizes to its OWN text + this modest padding — a shared
   min-width (tried in 0.15.8) forced every tab to match the widest one
   ("Diagrams"), which read as oversized and inconsistent for the two
   shorter tabs ("Charts", "Labels"). Left padding still leads right: a
   real screenshot showed every tab's FIRST letter missing without it (the
   native Windows tab style's own left inset fights a custom QSS one); the
   extra left room, plus the leading space in each tab's label text (see
   StudioDockWidget._build_ui), gives that inset something other than a
   real letter to eat into. The elide-fallback set in _build_ui
   (ElideRight) is the safety net for the rare case this still isn't quite
   enough on an unusual font — a graceful "…" instead of a raw clip.
   0.15.11's shorter (3px) vertical padding didn't land well — reverted the
   height back to 0.15.10's 10px, and scaled the horizontal padding up by
   the requested ×1.2 from that same 0.15.10 baseline (16/20 → 19/24). */
QTabBar::tab { background: #eef1f4; color: #5b6b73; padding: 10px 19px 10px 24px;
               margin-right: 4px; font-weight: 600;
               border-top-left-radius: 7px; border-top-right-radius: 7px; }
/* REVERTED (0.15.9 → 0.15.10): a QSS border-top accent stripe on the
   selected tab covered part of the text with a white strip on a real
   Windows screenshot — this native "windowsvista" tab style has already
   shown once (0.15.6, the missing-first-letter bug) that it does not
   reliably honour a custom QSS box-model addition; adding border-top most
   likely grew the box by 3px without the native sizeFromContents
   calculation reserving matching space, pushing the text down into the
   zone the content pane below already owns. Back to a background/colour
   difference only — no border property at all — which is exactly what
   shipped from 0.15.0 through 0.15.8 without this complaint. Lesson: on
   THIS specific tab bar, treat any new border/padding/margin property as
   suspect until proven on a real screenshot, not just headless. */
QTabBar::tab:selected { background: #ffffff; color: #16323f; }
QTabBar::tab:hover:!selected { background: #e7ebee; color: #16323f; }

/* ── text + form labels (pinned dark so they never inherit a light palette
      text colour and vanish on the white cards) ── */
QLabel { color: #2c3e46; background: transparent; }
/* colour only on QCheckBox itself: any background/border here makes Qt draw
   the box through the stylesheet and the indicator vanishes (TRAPS 3.7). The
   indicator gets its own rules below, so it reads the same under Fusion,
   windowsvista and the Night Mapping / Blend of Gray themes (which otherwise
   paint a dark box on the white card). */
QCheckBox { color: #2c3e46; }
QCheckBox:disabled { color: #9aa6ae; }
QCheckBox::indicator, QListWidget::indicator {
    width: 13px; height: 13px; border: 1px solid #6f7f88; border-radius: 3px;
    background-color: #ffffff; }
/* the themes paint the unticked box with an image (Blend of Gray) or a dark
   fill (Night Mapping) at this specificity; the panel's own rules win */
QCheckBox::indicator:unchecked, QListWidget::indicator:unchecked {
    background-color: #ffffff; image: none; }
QCheckBox::indicator:hover, QListWidget::indicator:hover { border-color: #237a72; }
QCheckBox::indicator:checked, QListWidget::indicator:checked {
    background-color: #237a72; border-color: #237a72; @CHECK_IMAGE@ }
QCheckBox::indicator:disabled, QListWidget::indicator:disabled,
QCheckBox::indicator:unchecked:disabled, QListWidget::indicator:unchecked:disabled {
    background-color: #eef1f3; border-color: #c5ced4; image: none; }
QCheckBox::indicator:checked:disabled, QListWidget::indicator:checked:disabled {
    background-color: #a9c8c4; border-color: #a9c8c4; }

/* ── inputs: white field, dark text, teal selection — independent of the host
      palette so the dropdown popup is never black again ── */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QListWidget, QPlainTextEdit {
    background: #ffffff;
    color: #16323f;
    border: 1px solid #cbd3da;
    border-radius: 6px;
    padding: 3px 6px;
    selection-background-color: #237a72;
    selection-color: #ffffff;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #237a72;
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
    selection-background-color: #237a72;
    selection-color: #ffffff;
    outline: 0;
}
QComboBox QAbstractItemView::item { min-height: 22px; padding: 2px 4px; }
QListWidget::item { color: #16323f; }
QListWidget::item:selected { background: #237a72; color: #ffffff; }

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
    f"QPushButton {{ background-color: {_ACCENT}; border: 1px solid {_ACCENT_HOVER};"
    " color: #ffffff; font-weight: 600; padding: 7px 14px; border-radius: 8px; }"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
    "QPushButton:disabled { background-color: #a9c8c4; border-color: #a9c8c4; }"
)
# the single most-clicked action in the whole studio gets its own accent — a
# soft "yavru ağzı" (salmon) stroke around the same teal fill, so it reads as
# the primary action at a glance without changing its familiar colour
_RENDER_CHART_BTN_QSS = (
    f"QPushButton {{ background-color: {_ACCENT}; border: 2px solid #f2a488;"
    " color: #ffffff; font-weight: 600; padding: 6px 14px; border-radius: 8px; }"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; border-color: #f6bda8; }}"
    "QPushButton:disabled { background-color: #a9c8c4; border-color: #e4c6bb; }"
)


def _check_image_rule() -> str:
    """``image:`` for a ticked box: the check mark QGIS ships with its own
    Night Mapping theme, located through ``QgsApplication.uiThemes()`` (never a
    hard-coded install path). Without it a ticked box is still a filled teal
    square, so the state stays readable."""
    with suppress(Exception):  # an odd build without UI themes keeps the fill
        folder = QgsApplication.uiThemes().get("Night Mapping", "")
        path = os.path.join(folder, "icons", "qcheckbox-checked.svg") if folder else ""
        if path and os.path.isfile(path):
            return 'image: url("%s");' % path.replace("\\", "/")
    return ""


def _dock_qss() -> str:
    return _DOCK_QSS.replace("@CHECK_IMAGE@", _check_image_rule())


def _webkit_card(engine_label: str, chart_type: str = "") -> str:
    """The panel page for an engine the legacy QtWebKit view cannot run (no
    QtWebEngine in this QGIS). Plain HTML/CSS so the old fork renders it; the
    real chart is still exported and opened from the Export menu."""
    engine = html_lib.escape(engine_label)
    what = html_lib.escape(f"{chart_type} chart" if chart_type else "chart")
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Open in browser"
        "</title><style>html,body{margin:0;padding:0;background:#fbfbfd;"
        "color:#16323f;font-family:'Segoe UI',system-ui,Arial,sans-serif}"
        ".card{max-width:440px;margin:24px auto;background:#fff;border:1px solid"
        " #d8dee4;border-radius:12px;padding:18px 20px}h2{margin:0 0 10px;"
        "font-size:16px;color:#237a72}p{margin:8px 0;font-size:13px;"
        "line-height:1.5}.muted{color:#5f6e76;font-size:12px}</style></head>"
        f"<body><div class='card'><h2>Open this {what} in your browser</h2>"
        f"<p>The <b>{engine}</b> engine needs a modern web view. This QGIS build"
        " only ships the legacy <b>QtWebKit</b> viewer, which cannot run it, so"
        " the panel would stay blank.</p><p>Your chart is ready: choose"
        " <b>Export &#9662; &rarr; Open in browser</b> under the panel, or"
        " <b>Export &#9662; &rarr; HTML file</b>.</p><p class='muted'>For a chart"
        " inside the panel now, pick the <b>ECharts</b> engine under Advanced."
        f" To run {engine} here, install QtWebEngine for QGIS (the"
        " python3-qt5-webengine package in OSGeo4W).</p></div></body></html>")


class _FlowLayout(QLayout):
    """Lays its items out left to right and wraps onto new lines, so a row of
    check boxes or colour swatches never forces the panel wider than the
    dock (the Qt "flow layout" example)."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    def _arrange(self, rect, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        x, y, line = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y, line = area.x(), y + line + self._gap, 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y() + margins.bottom()


class _Fold(QWidget):
    """A titled section that opens and closes; closed by default so the first
    screen leads with the layer and the fields."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setObjectName("o2vizFold")
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.toggled.connect(self.set_open)
        lay.addWidget(self.toggle)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(4, 0, 0, 4)
        self.content.setSpacing(6)
        self.body.setVisible(False)
        lay.addWidget(self.body)

    def set_open(self, on: bool) -> None:
        on = bool(on)
        if self.toggle.isChecked() != on:
            self.toggle.setChecked(on)  # re-enters once through toggled
            return
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)

    def is_open(self) -> bool:
        return self.toggle.isChecked()


def _shrinkable(combo: QComboBox) -> None:
    """Let a combo shrink below its longest item (a long field or engine name
    must not force the panel wider than a narrow dock)."""
    combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(6)
    policy = combo.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
    combo.setSizePolicy(policy)


class _PlaceholderTint(QObject):
    """Keeps placeholder text at 5.3:1 on the white fields.

    The stylesheet engine derives placeholder text from ``color`` at half
    opacity (about 3:1 here) and re-applies it on every polish, so a palette
    set once is overwritten. This filter sets the colour again right after
    each polish (the Polish event follows the style's own polish)."""

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if event.type() in (QEvent.Type.Polish, QEvent.Type.StyleChange):
            palette = obj.palette()
            color = QColor(_MUTED_TEXT)
            if palette.color(QPalette.ColorRole.PlaceholderText) != color:
                palette.setColor(QPalette.ColorRole.PlaceholderText, color)
                obj.setPalette(palette)
        return False


def _readable_placeholder(widget, tint: QObject) -> None:
    widget.installEventFilter(tint)
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(_MUTED_TEXT))
    widget.setPalette(palette)


_RULE_VALUE = re.compile(
    r"""^\s*"?[^"=<>!]+?"?\s*=\s*(?:'((?:[^']|'')*)'|(-?\d+(?:\.\d+)?))\s*$""")


def layer_category_colors(layer) -> tuple[dict, str]:
    """``{category label: "#rrggbb"}`` from a categorized or rule-based style.

    Keys are the category values formatted the way chart categories are
    (``transform._key``) plus the legend labels, so a chart on the styled field
    finds its categories whichever form the engine meets. Returns the map and
    a note for the status line when nothing could be taken."""
    renderer = layer.renderer() if hasattr(layer, "renderer") else None
    if renderer is None:
        return {}, "this layer has no symbol style"
    kind = renderer.type()
    colors: dict[str, str] = {}
    if kind == "categorizedSymbol":
        categories = renderer.categories()  # keep the list alive while reading
        for category in categories:
            symbol = category.symbol()
            if symbol is None or not category.renderState():
                continue
            color = symbol.color().name()
            values = category.value()
            values = values if isinstance(values, list) else [values]
            for value in values:
                if value is None or value == "" or (
                        hasattr(value, "isNull") and value.isNull()):
                    continue  # the "all other values" class
                colors.setdefault(transform._key(value), color)
            label = category.label()
            if label:
                colors.setdefault(str(label), color)
    elif kind == "RuleRenderer":
        for rule in renderer.rootRule().descendants():
            symbol = rule.symbol()
            if symbol is None or not rule.active():
                continue
            color = symbol.color().name()
            match = _RULE_VALUE.match(rule.filterExpression() or "")
            if match:
                value = match.group(1).replace("''", "'") if match.group(1) is not None \
                    else match.group(2)
                colors.setdefault(value, color)
            if rule.label():
                colors.setdefault(str(rule.label()), color)
    else:
        return {}, "the layer's style has no categories (use a categorized or rule-based style)"
    if not colors:
        return {}, "the layer's style has no coloured categories"
    return colors, ""

CHART_TYPES = [
    ("bar", "Bar chart"),
    ("lollipop", "Lollipop chart"),
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
    ("ecdf", "ECDF (cumulative)"),
    ("lorenz", "Lorenz & Gini"),
]

# which controls matter per chart type:
#   (y, group, value_size, aggregate, bins, topn_sort, stacked, trend)
_CONTROLS = {
    "bar":       (True,  True,  False, True,  False, True,  True,  False),
    "lollipop":  (True,  True,  False, True,  False, True,  False, False),
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
    "ecdf":      (False, True,  False, False, False, False, False, False),
    "lorenz":    (False, True,  False, False, False, False, False, False),
}


def _vector_filter():
    """Scoped-enum-safe vector filter for QgsMapLayerComboBox (Qt5/Qt6)."""
    from qgis.core import QgsMapLayerProxyModel

    try:
        return QgsMapLayerProxyModel.VectorLayer
    except AttributeError:  # QGIS 4 scoped enums
        return QgsMapLayerProxyModel.Filter.VectorLayer


def _numeric_field_filter():
    """Scoped-enum-safe numeric filter for QgsFieldComboBox (Qt5/Qt6)."""
    try:
        return QgsFieldProxyModel.Numeric
    except AttributeError:  # QGIS 4 scoped enums
        return QgsFieldProxyModel.Filter.Numeric


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
        self._last_html: str | None = None   # the last real chart/dashboard page
        self._last_path: str | None = None   # the one page file of this dock
        self._last_extraction_info = None
        self._tmp_dir: str | None = None
        self._watched_layer = None
        self._suppress_refresh_until = 0.0
        self._custom_palette: list[str] | None = None
        self._custom_spec_enabled = False
        self._prev_palette_index = 0
        self._preset_library: dict[str, dict] = {}
        # what the panel shows: None | "chart" | "explore" | "guide" | "card"
        # (card = the legacy-WebKit explainer standing in for a real chart)
        self._page_kind: str | None = None
        self._page_version = 0
        self._embedded = False
        self._exportable = False      # the shown page answers o2vizExport
        self._chart_current = False   # False after a failed render
        self._last_action = "render"  # what a stale redraw repeats
        self._charted_layer_id: str | None = None
        self._charted_links: list = []
        self._stale = False
        self._detach_downloads = None
        self._cleaned = False
        self._stale_timer = QTimer(self)
        self._stale_timer.setSingleShot(True)
        self._stale_timer.setInterval(STALE_REDRAW_MS)
        self._stale_timer.timeout.connect(self._redraw_stale)
        self.bridge = SelectionBridge()
        self.bridge.on_selected = self._on_chart_drove_selection
        self._build_ui()
        self._restore_last_setup()

    # ───────────────────────── UI ─────────────────────────

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setProperty("class", "o2vizCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        if title:
            head = QLabel(title)
            head.setProperty("class", "o2vizCardTitle")
            head.setWordWrap(True)
            lay.addWidget(head)
        return card, lay

    def _field_combo(self) -> QgsFieldComboBox:
        combo = QgsFieldComboBox()
        combo.setAllowEmptyFieldName(True)
        return combo

    @staticmethod
    def _dot_icon(color: str) -> QIcon:
        """A small filled circle, used as the active tab's indicator.

        Deliberately an ICON, not a border/padding QSS property: this tab
        bar's native "windowsvista" style has twice (0.15.6, 0.15.9) shown
        it does not reliably honour a custom QSS box-model addition, but
        tab icons are a first-class QTabBar feature Qt paints in its own
        dedicated, native-theme-compatible slot — it can't collide with the
        box-model math a border does.
        """
        size = 8
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, size, size)
        painter.end()
        return QIcon(pixmap)

    def _sync_tab_dot(self, *_args) -> None:
        """Show a small teal dot on the active tab only — the "nice effect"
        for which tab is open, without touching border/padding (see
        _dot_icon)."""
        if not hasattr(self, "tabs"):
            return
        current = self.tabs.currentIndex()
        for i in range(self.tabs.count()):
            self.tabs.setTabIcon(i, self._tab_dot_icon if i == current else QIcon())

    def _build_ui(self) -> None:
        # outer = scrolling panel + the pinned action bar and status line
        outer_widget = QWidget()
        outer_widget.setObjectName("o2vizRoot")
        outer_widget.setStyleSheet(_dock_qss())
        outer = QVBoxLayout(outer_widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        container = QWidget()
        container.setObjectName("o2vizContent")
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
        tagline.setWordWrap(True)
        head_text.addWidget(tagline)
        head_row.addLayout(head_text, 1)
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
        # Each tab is sized to its own (short) text — do NOT force expanding
        # or a minimum width here: a forced minimum cannot shrink on a
        # narrow dock, and with expanding on, Qt held the whole bar at that
        # forced size regardless of the dock's actual width (verified: bar
        # width stayed fixed from 140px to 360px), so the excess silently
        # ran off the edge — a hard mid-glyph clip, worse than the original
        # bug. Left at Qt's default: `usesScrollButtons` is already on for
        # this style, so if the 3 short tabs genuinely don't fit, small
        # arrows let you reach the rest instead of any tab ever being
        # rendered smaller than its own text. ElideRight is still set as a
        # last-resort fallback so any edge case degrades to "…", never a
        # raw pixel clip.
        #
        # A real screenshot on Windows QGIS showed every tab missing its
        # FIRST letter ("Charts"→"harts", "Diagrams"→"iagram", "Labels"→
        # "abels") — a known Qt/Windows quirk: the native "windowsvista"
        # style paints QTabBar tabs through the real Windows theme engine
        # (UxTheme), which reserves its own internal left inset that a
        # custom QSS stylesheet doesn't fully override, so the leading
        # glyph is painted under the tab's rounded left edge. (Tried
        # forcing this tab bar onto the Fusion style, which draws purely
        # from QSS geometry and would have sidestepped the native theme
        # entirely — reverted: it segfaulted on dock teardown in real
        # QGIS and the applied style didn't even verify as Fusion, likely
        # from mixing an explicit setStyle() with the container's own
        # QSS-driven QStyleSheetStyle proxy. Not worth the crash risk.)
        # Two purely-QSS/string fixes instead, layered for safety since
        # this can't be reproduced headless (no native Windows theme
        # engine under offscreen — verified against the screenshot, not a
        # pixel test): extra LEFT padding beyond the right, and a leading
        # space in each label, so whatever gets eaten from the left is the
        # padding/space, not a real letter, regardless of the exact cause.
        tabbar = self.tabs.tabBar()
        with suppress(Exception):
            tabbar.setElideMode(Qt.TextElideMode.ElideRight)
        # "Map diagrams" ran tight against real desktop font metrics on a
        # narrow dock — "Diagrams" alone reads just as clearly next to
        # "Charts" and "Labels" (the tab's own card title inside still says
        # "Map diagrams — on canvas" in full)
        for page, label in ((self._build_charts_tab(), " Charts"),
                            (self._build_diagrams_tab(), " Diagrams"),
                            (self._build_labels_tab(), " Labels")):
            # pin a light page background so a dark host *stylesheet* (e.g. a
            # Night-Mapping UI theme that sets QWidget{background:dark}) can't
            # bleed through the chart area or the gaps around the cards
            page.setObjectName("o2vizTabPage")
            self.tabs.addTab(page, label)
        # a small teal dot marks the active tab (see _dot_icon/_sync_tab_dot)
        self.tabs.setIconSize(QSize(8, 8))
        self._tab_dot_icon = self._dot_icon(_ACCENT)
        self.tabs.currentChanged.connect(self._sync_tab_dot)
        self._sync_tab_dot()
        root.addWidget(self.tabs, 1)

        # The dock can be far shorter than the panel's natural content height
        # (many form rows across three tabs) — without this, QGIS simply
        # squashes everything and the bottom rows become unreachable. Wrap
        # the panel in a scroll area: widgetResizable=True still lets the tab
        # area stretch to fill a tall dock, but a short dock scrolls instead
        # of clipping. Every row can shrink to a 350 px dock (wrapping rows,
        # shrinkable combos, exports in one menu), so the horizontal bar
        # stays AsNeeded only as a last resort for an unusual font.
        scroll = QScrollArea()
        scroll.setObjectName("o2vizScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea#o2vizScroll { background: #fbfbfd; border: none; }")
        scroll.setWidget(container)
        self._scroll = scroll
        outer.addWidget(scroll, 1)

        # pinned under the scrolling panel: the open tab's primary action and
        # the status line stay in reach at any dock height
        bar = QWidget()
        bar.setObjectName("o2vizActionBar")
        bar_lay = QVBoxLayout(bar)
        bar_lay.setContentsMargins(10, 6, 10, 6)
        bar_lay.setSpacing(4)
        self.action_stack = QStackedWidget()
        self.action_stack.addWidget(self._build_chart_actions())
        self.action_stack.addWidget(self._build_apply_actions(
            self._apply_diagram, self._clear_diagram, "Remove diagrams from this layer"))
        self.action_stack.addWidget(self._build_apply_actions(
            self._apply_labels, self._clear_labels, "Remove labels from this layer"))
        self.action_stack.setSizePolicy(QSizePolicy.Policy.Preferred,
                                        QSizePolicy.Policy.Maximum)
        bar_lay.addWidget(self.action_stack)
        self.status = QLabel("Ready")
        self.status.setObjectName("o2vizStatus")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bar_lay.addWidget(self.status)
        outer.addWidget(bar, 0)
        self.tabs.currentChanged.connect(self.action_stack.setCurrentIndex)

        for combo in outer_widget.findChildren(QComboBox):
            _shrinkable(combo)
        self._placeholder_tint = _PlaceholderTint(self)
        for edit in outer_widget.findChildren(QLineEdit) + outer_widget.findChildren(
                QPlainTextEdit):
            _readable_placeholder(edit, self._placeholder_tint)
        self.setWidget(outer_widget)
        self._on_layer_changed(self.layer_combo.currentLayer())
        self._sync_engine_types()
        self._sync_controls()
        self._sync_swatches()
        self._sync_export_actions()

    def _build_chart_actions(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.render_btn = QPushButton("Render chart")
        self.render_btn.setStyleSheet(_RENDER_CHART_BTN_QSS)
        self.render_btn.setToolTip("Draw the chart from the settings above")
        self.render_btn.clicked.connect(self._render)
        row.addWidget(self.render_btn, 1)
        # every export in one menu (the old row of eight buttons made the
        # panel 750-800 px wide — GitHub issue #2)
        self.export_menu_btn = QToolButton()
        self.export_menu_btn.setObjectName("o2vizExportMenu")
        self.export_menu_btn.setText("Export ▾")
        self.export_menu_btn.setToolTip("Save or open the chart shown in the panel")
        self.export_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.export_menu_btn)
        self.export_btn = menu.addAction("HTML file (interactive)…")
        self.export_btn.triggered.connect(self._export_html)
        self.export_svg_btn = menu.addAction("SVG (vector)…")
        self.export_svg_btn.triggered.connect(self._export_svg)
        self.export_png_btn = menu.addAction("PNG image…")
        self.export_png_btn.triggered.connect(self._export_png)
        self.export_pdf_btn = menu.addAction("PDF (vector)…")
        self.export_pdf_btn.triggered.connect(self._export_pdf)
        menu.addSeparator()
        self.browser_btn = menu.addAction("Open in browser ↗")
        self.browser_btn.setToolTip(
            "Open the current chart in your system web browser "
            "(use this if the embedded panel stays blank)")
        self.browser_btn.triggered.connect(self._open_in_browser)
        menu.setToolTipsVisible(True)
        self.export_menu = menu
        self.export_menu_btn.setMenu(menu)
        row.addWidget(self.export_menu_btn, 0)
        return page

    def _build_apply_actions(self, apply_slot, clear_slot, clear_tip: str) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        apply_btn = QPushButton("Apply to layer")
        apply_btn.setStyleSheet(_RENDER_BTN_QSS)
        apply_btn.clicked.connect(apply_slot)
        row.addWidget(apply_btn, 1)
        clear_btn = QPushButton("Clear")
        clear_btn.setToolTip(clear_tip)
        clear_btn.clicked.connect(clear_slot)
        row.addWidget(clear_btn, 0)
        return page

    # ── shared Data card ──

    def _build_data_card(self) -> QFrame:
        data_card, data_lay = self._card("Data")
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(_vector_filter())
        self.layer_combo.layerChanged.connect(self._on_layer_changed)
        QgsProject.instance().layersAdded.connect(self._on_project_layers_added)
        data_lay.addWidget(self.layer_combo)
        row = _FlowLayout(spacing=10)
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
        """Charts tab, in the order a first-time user needs it: one-click
        Suggest / Explore, then type and fields, then style. The engine and
        every refinement live under "Advanced" (folded), the Explore tiles
        under "Explore options"; the chart view sits at the bottom and the
        panel scrolls to it after each render."""
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(8)

        quick = QHBoxLayout()
        quick.setSpacing(6)
        self.suggest_btn = QPushButton("💡 Suggest")
        self.suggest_btn.setToolTip(
            "Let 02viz pick the most insightful chart for this layer's fields, "
            "configure the controls and render it")
        self.suggest_btn.clicked.connect(self._suggest_chart)
        quick.addWidget(self.suggest_btn, 1)
        self.explore_btn = QPushButton("✨ Explore layer")
        self.explore_btn.setToolTip(
            "One click: profile every field and build a full interactive dashboard")
        self.explore_btn.setStyleSheet(
            "QPushButton { background-color: #16323f; border: 1px solid #16323f;"
            " color: #ffffff; font-weight: 600; padding: 6px 10px; border-radius: 8px; }"
            "QPushButton:hover { background-color: #1f4254; }")
        self.explore_btn.clicked.connect(self._explore)
        quick.addWidget(self.explore_btn, 1)
        outer.addLayout(quick)

        chart_card, chart_lay = self._card("Chart")
        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # the engine decides which chart types are drawable; it is created
        # first (its signal wired once type_combo exists) and shown under
        # Advanced — ECharts draws every type, so most users never need it
        self.engine_combo = QComboBox()
        for eng in engines():
            label = eng.label if eng.available() else f"{eng.label}  (install…)"
            self.engine_combo.addItem(label, eng.id)
        self.engine_combo.setToolTip(
            "Vendored JS engines work offline with no setup; advanced engines "
            "(matplotlib/seaborn) need the library in the QGIS Python for "
            "publication-grade static charts")

        self.type_combo = QComboBox()
        for key, label in CHART_TYPES:
            self.type_combo.addItem(label, key)
        self.type_combo.currentIndexChanged.connect(self._sync_controls)
        form.addRow("Type", self.type_combo)
        self.engine_combo.currentIndexChanged.connect(self._sync_engine_types)

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

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("(layer name)")
        self.title_edit.setToolTip("Override the chart title; empty uses the layer name")
        form.addRow("Title", self.title_edit)

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
        chart_lay.addLayout(form)

        # inline, embedded swatch editor — click a swatch to recolour, +/− to
        # resize the palette; any edit switches to a custom palette. No modal.
        # A wrapping row, so 16 swatches never widen the panel.
        self._swatch_host = QWidget()
        self._swatch_row = _FlowLayout(self._swatch_host, spacing=4)
        chart_lay.addWidget(self._swatch_host)

        self.layer_colors_check = QCheckBox("Use layer colours")
        self.layer_colors_check.setToolTip(
            "Colour the chart's categories with the layer's own symbol colours "
            "(categorized or rule-based style). Categories the style does not "
            "list keep the palette colours.")
        chart_lay.addWidget(self.layer_colors_check)
        outer.addWidget(chart_card)

        # ── Advanced (folded): engine, ordering, overlays, animation, facets,
        #    custom Vega-Lite spec and presets ──
        adv_card, adv_lay = self._card("")
        adv_lay.setContentsMargins(10, 4, 10, 6)
        self.advanced_fold = _Fold("Advanced")
        self.advanced_fold.toggle.setToolTip(
            "Engine, ordering, reference lines, animation, small multiples, "
            "a custom Vega-Lite spec and saved presets")
        adv_lay.addWidget(self.advanced_fold)
        afl = self.advanced_fold.content
        aform = QFormLayout()
        aform.setHorizontalSpacing(8)
        aform.setVerticalSpacing(6)
        aform.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        aform.addRow("Engine", self.engine_combo)

        self.topn_spin = QSpinBox()
        self.topn_spin.setRange(0, 200)
        self.topn_spin.setValue(0)
        self.topn_spin.setSpecialValueText("all")
        self.topn_spin.setToolTip("Keep the N largest categories, collapse the rest into 'Other'")
        aform.addRow("Top N", self.topn_spin)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("natural order", "natural")
        self.sort_combo.addItem("value ↓", "value_desc")
        self.sort_combo.addItem("value ↑", "value_asc")
        aform.addRow("Sort", self.sort_combo)

        self.animate_combo = self._field_combo()
        self.animate_combo.setToolTip(
            "Play the chart through this field's values — a bar-chart race, "
            "Gapminder bubbles, composition over the years. ECharts / Plotly; "
            "bar · line · area · scatter · bubble · pie.")
        aform.addRow("Animate by ▶", self.animate_combo)
        self.speed_combo = QComboBox()
        for _lbl, _ms in (("Slow", 1600), ("Medium", 900), ("Fast", 450)):
            self.speed_combo.addItem(_lbl, _ms)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.setToolTip("Animation speed (time spent on each frame)")
        aform.addRow("Play speed", self.speed_combo)
        self.facet_combo = self._field_combo()
        self.facet_combo.setToolTip(
            "Small multiples: one panel per value of this field, all sharing one "
            f"value axis and one colour key. Up to {_FACET_CAP} panels (the largest "
            "groups). All engines; bar · line · area · scatter · bubble · pie. "
            "Clear Animate by to use it.")
        aform.addRow("Facet by ▦", self.facet_combo)
        self.animate_combo.fieldChanged.connect(self._sync_animate)
        self.facet_combo.fieldChanged.connect(self._sync_animate)
        afl.addLayout(aform)

        flags = _FlowLayout(spacing=10)
        self.stacked_check = QCheckBox("Stacked")
        flags.addWidget(self.stacked_check)
        self.trend_check = QCheckBox("Trend line")
        flags.addWidget(self.trend_check)
        self.link_check = QCheckBox("Click selects on map")
        self.link_check.setChecked(True)
        flags.addWidget(self.link_check)
        afl.addLayout(flags)

        # orientation and axis direction (GitHub issue #1), plus the race order
        axes = _FlowLayout(spacing=10)
        self.horizontal_check = QCheckBox("Horizontal bars")
        self.horizontal_check.setToolTip(
            "Bars run left to right with the categories down the side, first "
            "category on top (bar, lollipop and histogram)")
        axes.addWidget(self.horizontal_check)
        self.reverse_x_check = QCheckBox("Reverse X axis")
        self.reverse_x_check.setToolTip("Flip the horizontal axis")
        axes.addWidget(self.reverse_x_check)
        self.reverse_y_check = QCheckBox("Reverse Y axis")
        self.reverse_y_check.setToolTip("Flip the vertical axis")
        axes.addWidget(self.reverse_y_check)
        self.race_check = QCheckBox("Re-rank bars each frame")
        self.race_check.setChecked(True)
        self.race_check.setToolTip(
            "Animated bar chart: sort the bars again at every frame so the "
            "leader moves to the top (a bar-chart race). Untick to keep one order.")
        axes.addWidget(self.race_check)
        afl.addLayout(axes)

        # reference & statistics overlays (bar/line/area/scatter/bubble)
        afl.addWidget(QLabel("Reference lines"))
        refs = _FlowLayout(spacing=10)
        self.ov_mean_check = QCheckBox("Mean")
        self.ov_median_check = QCheckBox("Median")
        self.ov_sigma_check = QCheckBox("±1σ")
        self.ov_iqr_check = QCheckBox("IQR")
        self.ov_mean_check.setToolTip("Horizontal line at the mean of the plotted values")
        self.ov_median_check.setToolTip("Horizontal line at the median")
        self.ov_sigma_check.setToolTip("Shaded band one standard deviation either side of the mean")
        self.ov_iqr_check.setToolTip("Shaded band across the inter-quartile range (Q1–Q3)")
        for _c in (self.ov_mean_check, self.ov_median_check,
                   self.ov_sigma_check, self.ov_iqr_check):
            refs.addWidget(_c)
        self.ov_target_edit = QLineEdit()
        self.ov_target_edit.setPlaceholderText("Target…")
        self.ov_target_edit.setFixedWidth(84)
        self.ov_target_edit.setToolTip(
            "Draw a reference line at this value (leave blank for none)")
        refs.addWidget(self.ov_target_edit)
        afl.addLayout(refs)

        self.custom_spec_check = QCheckBox("Custom Vega-Lite spec")
        self.custom_spec_check.setToolTip(
            "Edit the generated Vega-Lite JSON before rendering (Vega-Lite engine)")
        self.custom_spec_check.toggled.connect(self._sync_custom_spec)
        afl.addWidget(self.custom_spec_check)
        self.custom_spec_edit = QPlainTextEdit()
        self.custom_spec_edit.setFixedHeight(150)
        self.custom_spec_edit.setPlaceholderText("Paste or edit a Vega-Lite JSON object")
        self.custom_spec_edit.setVisible(False)
        afl.addWidget(self.custom_spec_edit)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip(
            "Recall a saved chart setup, including fields, styling and overlays")
        preset_row.addWidget(self.preset_combo, 1)
        afl.addLayout(preset_row)
        preset_btns = QHBoxLayout()
        self.preset_load_btn = QPushButton("Load")
        self.preset_load_btn.clicked.connect(self._load_selected_preset)
        preset_btns.addWidget(self.preset_load_btn)
        self.preset_save_btn = QPushButton("Save…")
        self.preset_save_btn.setToolTip("Save the current chart setup as a preset")
        self.preset_save_btn.clicked.connect(self._save_preset)
        preset_btns.addWidget(self.preset_save_btn)
        self.preset_delete_btn = QPushButton("Delete")
        self.preset_delete_btn.clicked.connect(self._delete_preset)
        preset_btns.addWidget(self.preset_delete_btn)
        preset_btns.addStretch(1)
        afl.addLayout(preset_btns)
        self.preset_combo.currentIndexChanged.connect(self._sync_preset_buttons)
        self._read_presets()
        outer.addWidget(adv_card)

        # ── Explore options (folded): dashboard tiles + play axis ──
        exp_card, exp_lay = self._card("")
        exp_lay.setContentsMargins(10, 4, 10, 6)
        self.explore_fold = _Fold("Explore options")
        self.explore_fold.toggle.setToolTip(
            "Which tiles ✨ Explore layer builds, and an optional play axis")
        exp_lay.addWidget(self.explore_fold)
        efl = self.explore_fold.content
        self.tile_picker = QListWidget()
        self.tile_picker.setObjectName("o2vizTilePicker")
        self.tile_picker.setFlow(QListView.Flow.LeftToRight)
        self.tile_picker.setWrapping(True)
        self.tile_picker.setResizeMode(QListView.ResizeMode.Adjust)
        self.tile_picker.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # a narrow dock wraps the tiles onto more rows than fit: scroll then
        self.tile_picker.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tile_picker.setMinimumHeight(58)
        self.tile_picker.setMaximumHeight(110)
        self.tile_picker.setMinimumWidth(60)
        for _label, _section in (("KPI row", "kpis"), ("Field table", "fields"), ("Count bars", "count_bars"), ("Histograms", "histograms"), ("Correlation matrix", "corr_matrix"), ("Scatter + trend", "scatter_trend"), ("Normalised box plot", "normalised_box"), ("Insights", "insights")):
            _item = QListWidgetItem(_label)
            _item.setData(Qt.ItemDataRole.UserRole, _section)
            _item.setFlags(_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            _item.setCheckState(Qt.CheckState.Checked)
            self.tile_picker.addItem(_item)
        efl.addWidget(self.tile_picker)
        explore_anim_row = QHBoxLayout()
        explore_anim_row.addWidget(QLabel("Animate by ▶"))
        self.explore_animate_combo = self._field_combo()
        self.explore_animate_combo.setToolTip(
            "Play the whole Explore dashboard through this field's values (years, "
            "phases, survey waves): count bars, histograms, the scatter and the Rows / "
            "Complete cards step together on one shared play bar. The correlation "
            "matrix and box plot keep showing all rows.")
        explore_anim_row.addWidget(self.explore_animate_combo, 1)
        efl.addLayout(explore_anim_row)
        outer.addWidget(exp_card)

        self._view_slot = QVBoxLayout()
        self._view_placeholder = QLabel(
            "Pick a layer, choose a chart type and press Render chart."
        )
        self._view_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view_placeholder.setWordWrap(True)
        self._view_placeholder.setStyleSheet(f"color: {_MUTED_TEXT}; padding: 22px;")
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
        diag_intro = QLabel(
            "Draw a diagram on every feature, on the map canvas, "
            "coloured with the studio palette.")
        diag_intro.setWordWrap(True)
        c.addWidget(diag_intro)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Type"))
        self.diag_type_combo = QComboBox()
        for key in diagrams.DIAGRAM_TYPES:
            self.diag_type_combo.addItem(diagrams.DIAGRAM_LABELS[key], key)
        trow.addWidget(self.diag_type_combo, 1)
        c.addLayout(trow)
        fields_label = QLabel("Fields (numeric — slices / bars):")
        fields_label.setWordWrap(True)
        c.addWidget(fields_label)
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
        srow.addWidget(QLabel("Opacity"))
        self.diag_opacity_spin = QSpinBox()
        self.diag_opacity_spin.setRange(10, 100)
        self.diag_opacity_spin.setValue(100)
        self.diag_opacity_spin.setSuffix("%")
        srow.addWidget(self.diag_opacity_spin)
        srow.addStretch(1)
        c.addLayout(srow)

        szrow = QHBoxLayout()
        szrow.addWidget(QLabel("Size by"))
        self.diag_size_field_combo = self._field_combo()
        self.diag_size_field_combo.setFilters(_numeric_field_filter())
        self.diag_size_field_combo.setToolTip(
            "Proportional symbols: scale each feature's diagram between a small "
            "and a full-size diagram by this field's value, so a population or "
            "magnitude field reads at a glance instead of every feature looking "
            "equally big. Leave empty for a fixed size.")
        szrow.addWidget(self.diag_size_field_combo, 1)
        c.addLayout(szrow)

        orow = QHBoxLayout()
        self.diag_avoid_overlap_check = QCheckBox("Hide crowded diagrams")
        self.diag_avoid_overlap_check.setToolTip(
            "Avoid overlaps: let QGIS drop diagrams that would collide instead "
            "of always drawing every one of them regardless of space.")
        orow.addWidget(self.diag_avoid_overlap_check)
        orow.addStretch(1)
        c.addLayout(orow)

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
        self.diag_hint.setStyleSheet(f"color: {_MUTED_TEXT}; font-size: 11px;")
        c.addWidget(self.diag_hint)
        # Apply to layer / Clear are pinned under the panel (_build_apply_actions)
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
        label_intro = QLabel(
            "Turn fields into well-placed labels — round numbers, stack a second "
            "line, add units, or write your own expression.")
        label_intro.setWordWrap(True)
        c.addWidget(label_intro)
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
        # a long expression has no spaces to wrap at: let the preview clip
        # (it stays selectable) instead of widening the panel
        self.label_preview.setSizePolicy(QSizePolicy.Policy.Ignored,
                                         QSizePolicy.Policy.Preferred)
        self.label_preview.setMinimumWidth(40)
        c.addWidget(self.label_preview)
        # Apply to layer / Clear are pinned under the panel (_build_apply_actions)
        outer.addWidget(card)
        outer.addStretch(1)
        return tab

    # ───────────────────────── wiring ─────────────────────────

    def _on_project_layers_added(self, *_args) -> None:
        QTimer.singleShot(0, self._resync_layer)

    def _resync_layer(self, *_args) -> None:
        """Give the field pickers the layer the combo really shows. On QGIS 4
        the combo selects the first layer added to an empty project but
        signals ``layerChanged(None)``, which left every field list empty."""
        if self._cleaned:
            return
        layer = self.layer_combo.currentLayer()
        if self.x_combo.layer() is not layer:
            self._on_layer_changed(layer)

    def _on_layer_changed(self, layer) -> None:
        for combo in (self.x_combo, self.y_combo, self.group_combo,
                      self.value_combo, self.animate_combo, self.facet_combo,
                      self.explore_animate_combo,
                      self.label_field_combo, self.label_field2_combo,
                      self.diag_size_field_combo):
            combo.setLayer(layer)
        self._refresh_diagram_fields(layer)
        self._sync_diag_hint()
        self._sync_label_preview()
        self._watch_layer(layer)

    def _watch_layer(self, layer) -> None:
        if self._watched_layer is not None:
            with suppress(RuntimeError, TypeError):  # layer gone / not connected
                self._watched_layer.selectionChanged.disconnect(self._on_selection_changed)
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

    # ── the charted layer: edits make the chart's feature ids stale ──

    _EDIT_SIGNALS = ("dataChanged", "afterCommitChanges", "afterRollBack",
                     "featureAdded", "featureDeleted", "attributeValueChanged",
                     "geometryChanged")

    def _watch_charted_layer(self, layer) -> None:
        """Follow edits on the layer the shown chart was drawn from."""
        for signal, slot in self._charted_links:
            with suppress(RuntimeError, TypeError):  # layer gone / not connected
                signal.disconnect(slot)
        self._charted_links = []
        self._charted_layer_id = layer.id() if layer is not None else None
        if layer is None:
            return
        for name in self._EDIT_SIGNALS:
            signal = getattr(layer, name, None)
            if signal is None:
                continue
            signal.connect(self._on_charted_layer_edited)
            self._charted_links.append((signal, self._on_charted_layer_edited))

    def _on_charted_layer_edited(self, *_args) -> None:
        """An edit or commit changed the charted layer: the chart's values and
        feature ids no longer hold. Mark it stale (a click must not select the
        wrong features) and redraw once the edits settle."""
        if self._page_kind not in ("chart", "explore", "card") or not self._chart_current:
            return
        self._stale = True
        self.bridge.bind(None)
        current = self.layer_combo.currentLayer()
        if current is None or current.id() != self._charted_layer_id:
            self.set_status("The charted layer changed — pick it again and "
                            "render to update the chart")
            return
        self.set_status("The layer changed — redrawing the chart…")
        self._stale_timer.start()

    def _redraw_stale(self) -> None:
        if not self._stale or self._cleaned:
            return
        if self._last_action == "explore":
            self._explore()
        else:
            self._render()

    def _on_page_loaded(self, ok: bool) -> None:
        if ok:
            # nudge the chart to re-measure now that the view is laid out —
            # the engine bodies also self-fit, this covers the first paint
            run_js(self._view_kind, self._view,
                   "window.dispatchEvent(new Event('resize'));")
            self._push_highlight()
            self._scroll_to_view()  # again: the layout has settled by now
        if self._page_kind in ("chart", "explore"):
            version = self._page_version
            if not ok or not eval_js(
                    self._view_kind, self._view, exports.PROBE_JS,
                    lambda value: self._on_export_probe(version, value)):
                self._on_export_probe(version, "missing")

    def _on_export_probe(self, version: int, value) -> None:
        """Enable SVG/PNG/PDF only for a loaded page that answers the export
        contract (pages from an engine without it keep them off, with a
        plain reason in the menu)."""
        if version != self._page_version:
            return  # an older page answered after a newer one started
        self._probe_version = version
        self._exportable = value == "ready"
        self._sync_export_actions()

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

    # Reusable chart presets

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> bool:
        index = combo.findData(value)
        if index < 0:
            return False
        combo.setCurrentIndex(index)
        return True

    def _chart_preset(self) -> dict:
        """Capture the reusable parts of the current chart configuration."""
        return {
            "engine": self.engine_combo.currentData(),
            "type": self.type_combo.currentData(),
            "theme": self.theme_combo.currentText(),
            "palette": self.palette_combo.currentText(),
            "custom_palette": (
                list(self._custom_palette) if self._custom_palette else []),
            "title": self.title_edit.text(),
            "fields": {
                "x": self.x_combo.currentField(),
                "y": self.y_combo.currentField(),
                "group": self.group_combo.currentField(),
                "value": self.value_combo.currentField(),
                "animate": self.animate_combo.currentField(),
                "facet": self.facet_combo.currentField(),
            },
            "speed": int(self.speed_combo.currentData()),
            "aggregation": self.agg_combo.currentText(),
            "bins": self.bins_spin.value(),
            "top_n": self.topn_spin.value(),
            "sort": self.sort_combo.currentData(),
            "selected_only": self.selected_only.isChecked(),
            "stacked": self.stacked_check.isChecked(),
            "trend": self.trend_check.isChecked(),
            "link": self.link_check.isChecked(),
            "mean": self.ov_mean_check.isChecked(),
            "median": self.ov_median_check.isChecked(),
            "sigma": self.ov_sigma_check.isChecked(),
            "iqr": self.ov_iqr_check.isChecked(),
            "target": self.ov_target_edit.text(),
            "custom_spec_enabled": self.custom_spec_check.isChecked(),
            "custom_spec": self.custom_spec_edit.toPlainText(),
        }

    def _read_presets(self) -> None:
        raw = QSettings().value(PRESET_SETTINGS_KEY, "")
        self._preset_library = presets.decode_library(raw)
        self._refresh_preset_combo()

    def _write_presets(self) -> None:
        QSettings().setValue(
            PRESET_SETTINGS_KEY, presets.encode_library(self._preset_library))

    def _refresh_preset_combo(self, selected: str = "") -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        if self._preset_library:
            for name in sorted(self._preset_library, key=str.casefold):
                self.preset_combo.addItem(name, name)
            index = self.preset_combo.findData(selected)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        else:
            self.preset_combo.addItem("No saved presets", None)
        self.preset_combo.blockSignals(False)
        self._sync_preset_buttons()

    def _sync_preset_buttons(self, *_args) -> None:
        available = self.preset_combo.currentData() in self._preset_library
        self.preset_load_btn.setEnabled(available)
        self.preset_delete_btn.setEnabled(available)

    def _save_preset(self) -> None:
        suggested = self.preset_combo.currentData() or (
            self.title_edit.text().strip()
            or self.type_combo.currentText().replace(" chart", ""))
        name, ok = QInputDialog.getText(
            self, "Save chart preset", "Preset name:", text=str(suggested))
        name = name.strip()
        if not ok or not name:
            return
        if (name not in self._preset_library
                and len(self._preset_library) >= presets.MAX_PRESETS):
            self.set_status(
                f"Preset limit reached ({presets.MAX_PRESETS}); delete one first")
            return
        if name in self._preset_library:
            answer = QMessageBox.question(
                self, "Replace chart preset",
                f'A preset named "{name}" already exists. Replace it?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        clean = presets.sanitize_preset(self._chart_preset())
        if clean is None:
            self.set_status("Could not save the current chart setup")
            return
        self._preset_library[name] = clean
        self._write_presets()
        self._refresh_preset_combo(name)
        self.set_status(f'Saved chart preset "{name}"')

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentData()
        if name not in self._preset_library:
            return
        answer = QMessageBox.question(
            self, "Delete chart preset", f'Delete the preset "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self._preset_library[name]
        self._write_presets()
        self._refresh_preset_combo()
        self.set_status(f'Deleted chart preset "{name}"')

    def _load_selected_preset(self) -> None:
        name = self.preset_combo.currentData()
        preset = self._preset_library.get(name)
        if preset is None:
            return
        problem, missing = self._apply_preset(preset)
        if problem:
            self.set_status(f'Preset "{name}" uses an unavailable {problem}')
            return
        suffix = (f" · missing fields cleared: {', '.join(sorted(set(missing)))}"
                  if missing else "")
        self.set_status(f'Loaded chart preset "{name}"{suffix}')

    def _apply_preset(self, preset: dict) -> tuple[str, list[str]]:
        """Put a sanitized preset into the widgets. Returns ``(problem,
        missing_fields)``; ``problem`` names what could not be applied
        ("engine" / "chart type"), empty on success."""
        if not self._set_combo_data(self.engine_combo, preset.get("engine")):
            return "engine", []
        self._sync_engine_types()
        if not self._set_combo_data(self.type_combo, preset.get("type")):
            return "chart type", []
        self._sync_controls()

        theme = self.theme_combo.findText(preset.get("theme", ""))
        if theme >= 0:
            self.theme_combo.setCurrentIndex(theme)
        custom_colors = preset.get("custom_palette", [])
        if preset.get("palette") == CUSTOM_PALETTE_LABEL and custom_colors:
            self._enter_custom(custom_colors)
        else:
            palette = self.palette_combo.findText(preset.get("palette", ""))
            if palette >= 0:
                self.palette_combo.setCurrentIndex(palette)

        self.title_edit.setText(preset.get("title", ""))
        layer = self.layer_combo.currentLayer()
        available = ({field.name() for field in layer.fields()}
                     if layer is not None else set())
        missing: list[str] = []
        fields = preset.get("fields", {})
        for key, combo in (
                ("x", self.x_combo), ("y", self.y_combo),
                ("group", self.group_combo), ("value", self.value_combo),
                ("animate", self.animate_combo), ("facet", self.facet_combo)):
            field = fields.get(key, "")
            if field and field not in available:
                missing.append(field)
                field = ""
            combo.setField(field)

        self._set_combo_data(self.speed_combo, preset.get("speed"))
        agg = self.agg_combo.findText(preset.get("aggregation", ""))
        if agg >= 0:
            self.agg_combo.setCurrentIndex(agg)
        self.bins_spin.setValue(preset.get("bins", self.bins_spin.value()))
        self.topn_spin.setValue(preset.get("top_n", self.topn_spin.value()))
        self._set_combo_data(self.sort_combo, preset.get("sort"))
        for key, widget in (
                ("selected_only", self.selected_only),
                ("stacked", self.stacked_check), ("trend", self.trend_check),
                ("link", self.link_check), ("mean", self.ov_mean_check),
                ("median", self.ov_median_check), ("sigma", self.ov_sigma_check),
                ("iqr", self.ov_iqr_check)):
            if key in preset:
                widget.setChecked(preset[key])
        self.ov_target_edit.setText(preset.get("target", ""))
        self.custom_spec_edit.setPlainText(preset.get("custom_spec", ""))
        self.custom_spec_check.setChecked(
            bool(preset.get("custom_spec_enabled"))
            and self.engine_combo.currentData() == "vegalite")
        self._sync_custom_spec()
        return "", missing

    # Last setup: restored when the panel opens again (also after a restart)

    def _save_last_setup(self) -> None:
        clean = presets.sanitize_preset(self._chart_preset())
        if clean is None:
            return
        layer = self.layer_combo.currentLayer()
        state = {
            "preset": clean,
            "layer": layer.id() if layer is not None else "",
            "tab": self.tabs.currentIndex(),
            "advanced": self.advanced_fold.is_open(),
            "explore": self.explore_fold.is_open(),
        }
        for key, box in self._state_checks():
            state[key] = box.isChecked()
        QSettings().setValue(LAST_SETUP_KEY, json.dumps(state, ensure_ascii=False))

    def _state_checks(self):
        """Check boxes the last setup keeps beyond the preset fields."""
        return (("layer_colors", self.layer_colors_check),
                ("horizontal", self.horizontal_check),
                ("reverse_x", self.reverse_x_check),
                ("reverse_y", self.reverse_y_check),
                ("race", self.race_check),
                ("live", self.auto_refresh))

    def _restore_last_setup(self) -> None:
        raw = QSettings().value(LAST_SETUP_KEY, "")
        try:
            state = json.loads(raw) if isinstance(raw, str) and raw else {}
        except ValueError:
            state = {}
        if not isinstance(state, dict):
            return
        layer_id = state.get("layer")
        if isinstance(layer_id, str) and layer_id:
            layer = QgsProject.instance().mapLayer(layer_id)
            if isinstance(layer, QgsVectorLayer):
                self.layer_combo.setLayer(layer)
        preset = presets.sanitize_preset(state.get("preset"))
        if preset is not None:
            self._apply_preset(preset)
        for key, box in self._state_checks():
            if isinstance(state.get(key), bool):
                box.setChecked(state[key])
        for key, fold in (("advanced", self.advanced_fold),
                          ("explore", self.explore_fold)):
            if isinstance(state.get(key), bool):
                fold.set_open(state[key])
        tab = state.get("tab")
        if isinstance(tab, int) and not isinstance(tab, bool) \
                and 0 <= tab < self.tabs.count():
            self.tabs.setCurrentIndex(tab)

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        with suppress(RuntimeError):  # widgets already torn down
            self._save_last_setup()
        super().hideEvent(event)

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
        self._sync_custom_spec()

    def _sync_custom_spec(self, *_args) -> None:
        if hasattr(self, "custom_spec_check"):
            on = self.engine_combo.currentData() == "vegalite"
            self.custom_spec_check.setEnabled(on)
            self.custom_spec_edit.setVisible(on and self.custom_spec_check.isChecked())

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
        self.horizontal_check.setEnabled(kind in HORIZONTAL_TYPES)
        ov_ok = kind in overlays.OVERLAY_TYPES
        for w in (self.ov_mean_check, self.ov_median_check, self.ov_sigma_check,
                  self.ov_iqr_check, self.ov_target_edit):
            w.setEnabled(ov_ok)
        self._sync_animate()

    def _sync_animate(self, *_args) -> None:
        """The play axis and the facet picker only light up when the chosen
        engine can animate / facet the chosen chart type (ECharts / Plotly ·
        bar·line·area·scatter·bubble·pie). They are mutually exclusive: a field
        in one disables the other until it is cleared."""
        if not hasattr(self, "facet_combo"):
            return
        eng = engines()[max(0, self.engine_combo.currentIndex())]
        kind = self.type_combo.currentData()
        can_anim = kind in eng.animates
        can_facet = kind in eng.facets
        facet_on = can_facet and bool(self.facet_combo.currentField())
        anim_on = can_anim and bool(self.animate_combo.currentField())
        self.animate_combo.setEnabled(can_anim and not facet_on)
        self.speed_combo.setEnabled(can_anim and not facet_on)
        self.facet_combo.setEnabled(can_facet and not anim_on)
        if hasattr(self, "race_check"):
            self.race_check.setEnabled(anim_on and kind == "bar")

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
        size_field = self.diag_size_field_combo.currentField()
        stats_fields = list(fields)
        if size_field and size_field not in stats_fields:
            stats_fields.append(size_field)
        field_stats: dict = {}
        size_range = None
        if normalize != "none" or size_field:
            try:
                cols = datasource.columns(layer, stats_fields,
                                          self.selected_only.isChecked())
            except ValueError as exc:
                self.set_status(str(exc))
                return
            for name in fields:
                st = stats.field_numeric_stats(cols[name])
                if st:
                    field_stats[name] = st
            if size_field:
                st = stats.field_numeric_stats(cols[size_field])
                if st:
                    size_range = (st["min"], st["max"])
        ok = diagrams.apply_diagram(
            layer, kind=kind, fields=fields,
            colors=list(self._current_theme()["palette"]),
            size_mm=self.diag_size_spin.value(),
            opacity=self.diag_opacity_spin.value() / 100.0,
            normalize=normalize, stats=field_stats,
            size_field=size_field if size_range else "", size_range=size_range,
            avoid_overlap=self.diag_avoid_overlap_check.isChecked())
        if not ok:
            self.set_status("Could not apply the diagram (no geometry?)")
            return
        self._refresh_canvas(layer)
        norm_txt = ("" if normalize == "none"
                    else ", " + expressions.NORMALIZE_LABELS[normalize].lower())
        size_txt = f", sized by {size_field}" if size_field and size_range else ""
        self.set_status(
            f"Applied {diagrams.DIAGRAM_LABELS[kind].lower()} diagram "
            f"({len(fields)} field{'s' if len(fields) != 1 else ''}{norm_txt}{size_txt}) "
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
        """Guarded evaluation of ``expr`` on the first feature, for the
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
        with suppress(Exception):  # don't let a typo silently produce no labels
            from qgis.core import QgsExpression
            parsed = QgsExpression(expr)
            if parsed.hasParserError():
                self.set_status("Expression error: "
                                + parsed.parserErrorString().strip())
                return
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
        with suppress(Exception):
            self.iface.layerTreeView().refreshLayerSymbology(layer.id())
        with suppress(Exception):
            self.iface.mapCanvas().refreshAllLayers()

    def _last_io_dir(self) -> str:
        """Return the last-used load/export folder, falling back to the user home."""
        value = QSettings().value("zero2viz/last_io_dir", "")
        return value if isinstance(value, str) and os.path.isdir(value) else os.path.expanduser("~")

    def _remember_io_dir(self, path: str) -> None:
        folder = os.path.dirname(path)
        if folder and os.path.isdir(folder):
            QSettings().setValue("zero2viz/last_io_dir", folder)

    def _load_external(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load external table", self._last_io_dir(),
            "Tables (*.csv *.xlsx *.ods *.gpkg *.dbf);;All files (*.*)")
        if not path:
            return
        self._remember_io_dir(path)
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
        facet = (self.facet_combo.currentField()
                 if self.facet_combo.isEnabled() else "")
        agg = self.agg_combo.currentText()
        sel = self.selected_only.isChecked()

        fields = [f for f in {x, y, group, value, animate, facet} if f]
        if not fields:
            self.set_status("Pick at least an X field")
            return None
        try:
            cols, fids, extraction = datasource.columns_with_ids_info(
                layer, fields, sel)
            self._last_extraction_info = extraction
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
        self._rows_note = ""

        builder = getattr(self, f"_spec_{kind}", None)
        data = builder(spec, cols, fids, x=x, y=y, group=group, value=value, agg=agg)
        if data is None:
            return None
        spec["data"] = data
        self._layer_colors_note = ""
        if self.layer_colors_check.isChecked():
            # §3 contract: engines colour the categories found in this map and
            # keep the palette for the rest
            colors, why = layer_category_colors(layer)
            if colors:
                spec.setdefault("options", {})["category_colors"] = colors
                self._layer_colors_note = " · layer colours"
            else:
                self._layer_colors_note = f" · layer colours not used: {why}"
        if self.custom_spec_check.isChecked() and eng.id == "vegalite":
            try:
                spec["custom_vl"] = json.loads(self.custom_spec_edit.toPlainText())
            except json.JSONDecodeError as exc:
                self.set_status(f"Custom spec JSON error at line {exc.lineno}: {exc.msg}")
                return None
        if animate and kind in eng.animates:
            frames = self._build_frames(
                spec, cols, fids, kind=kind, x=x, y=y, group=group,
                value=value, agg=agg, frame_field=animate)
            if frames is None:
                return None  # _build_frames sets the status
            spec["frames"] = frames
        elif facet and kind in eng.facets:
            facets = self._build_facets(
                spec, cols, fids, kind=kind, x=x, y=y, group=group,
                value=value, agg=agg, facet_field=facet)
            if facets is None:
                return None  # _build_facets sets the status
            spec["facets"] = facets
        else:
            # reference lines/bands apply to the static chart (a play axis tells
            # its own story, so overlays are skipped while animating)
            ov_opts = self._overlay_options(kind)
            if ov_opts:
                ovs = overlays.build_overlays(spec, ov_opts, spec["theme"])
                if ovs:
                    spec["overlays"] = ovs
        # §3 rendering options: orientation / axis direction (GitHub #1) and
        # whether an animated bar chart re-ranks every frame
        opts = {}
        if self.horizontal_check.isChecked() and kind in HORIZONTAL_TYPES:
            opts["horizontal"] = True
        if self.reverse_x_check.isChecked():
            opts["reverse_x"] = True
        if self.reverse_y_check.isChecked():
            opts["reverse_y"] = True
        if spec.get("frames") and kind == "bar":
            opts["race"] = self.race_check.isChecked()
        if opts:
            spec.setdefault("options", {}).update(opts)
        return spec

    def _overlay_options(self, kind: str) -> dict | None:
        """Read the reference-line controls into options for ``core.overlays``,
        or None when the type has no value axis or nothing is requested."""
        if kind not in overlays.OVERLAY_TYPES:
            return None
        opts = {"mean": self.ov_mean_check.isChecked(),
                "median": self.ov_median_check.isChecked(),
                "sigma": self.ov_sigma_check.isChecked(),
                "iqr": self.ov_iqr_check.isChecked()}
        text = self.ov_target_edit.text().strip()
        target = stats.to_float(text) if text else None
        if not (any(opts.values()) or target is not None):
            return None
        if target is not None:
            opts["target"] = target
        return opts

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
            # one slot per feature; NULL / non-numeric Y is left out, never 0
            cats, vals, ids = transform.raw_rows(cols[x], cols[y], fids)
            skipped = len(cols[x]) - len(cats)
            if not cats:
                self.set_status(f"No numeric values in '{y}'")
                return None
            if skipped:
                self._rows_note = (f" · {skipped} row{'s' if skipped != 1 else ''} "
                                   f"without a number in {y} left out")
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

    _spec_lollipop = _spec_bar
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
                                    cols.get(value, []), how, fids)
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

    def _spec_ecdf(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x:
            self.set_status("ECDF needs a numeric X field")
            return None
        order, buckets = self._group_buckets(cols[group] if group else None,
                                             cols[x], x)
        series = []
        for key in order:
            pts = stats.ecdf_points(buckets[key])
            if pts:
                series.append({"name": key, "points": pts})
        if not series:
            self.set_status(f"Need at least 2 distinct numeric values in '{x}'")
            return None
        spec["y_label"] = "cumulative %"
        return {"series": series}

    def _spec_lorenz(self, spec, cols, fids, *, x, y, group, value, agg):
        if not x:
            self.set_status("Lorenz & Gini needs a non-negative numeric X field")
            return None
        order, buckets = self._group_buckets(cols[group] if group else None,
                                             cols[x], x)
        series = []
        for key in order:
            built = stats.lorenz_points(buckets[key])
            if built is not None:
                pts, g = built
                series.append({"name": key, "gini": g, "points": pts})
        if not series:
            self.set_status(
                f"Lorenz & Gini needs ≥ 2 non-negative numeric values in '{x}' with positive sum")
            return None
        spec["y_label"] = "cumulative share (%)"
        return {"series": series}

    # ───────────────────────── animation (play axis) ─────────────────────────

    def _build_frames(self, spec, cols, fids, *, kind, x, y, group, value, agg,
                      frame_field):
        """Assemble the ``frames`` block for an animated chart. Validates the
        field roles, then delegates the slicing/alignment to the pure
        :func:`transform.build_frames` (so it stays testable headless)."""
        if kind in ("bar", "lollipop", "line", "area", "pie"):
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
            x=x, y=y, group=group, value=value, how=how, single_name=single,
            stacked=bool(spec.get("stacked")))
        if built is None:
            self.set_status("Animate-by needs ≥ 2 frames with chartable data")
            return None
        labels, datas, union, bounds = built
        spec["data"] = datas[0]
        return {"field": frame_field, "labels": labels, "datas": datas,
                "categories": union, "bounds": bounds,
                "interval": self.speed_combo.currentData() or 900}

    def _build_facets(self, spec, cols, fids, *, kind, x, y, group, value, agg,
                      facet_field):
        """Assemble the ``facets`` block for small multiples. Same field-role
        validation as animation; slicing and alignment live in the pure
        :func:`transform.build_facets`. ``spec["data"]`` keeps the whole
        dataset, so an engine without faceting still shows every row."""
        if kind in ("bar", "lollipop", "line", "area", "pie"):
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

        built = transform.build_facets(
            kind, cols, fids, cols.get(facet_field, []),
            x=x, y=y, group=group, value=value, how=how, single_name=single,
            cap=_FACET_CAP, stacked=bool(spec.get("stacked")))
        if built is None:
            self.set_status("Facet by needs ≥ 2 groups with chartable data")
            return None
        labels, datas, union, bounds, dropped = built
        return {"field": facet_field, "labels": labels, "datas": datas,
                "categories": union, "bounds": bounds,
                "columns": transform.facet_columns(len(labels)),
                "dropped": dropped}

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
                w.hide()
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
        self._swatch_host.updateGeometry()

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
                # the page's own toolbar downloads (ECharts / Plotly buttons)
                self._detach_downloads = exports.attach_downloads(
                    self._view_kind, self._view, self._on_page_download)
                self._view_placeholder.hide()
                self._view.setMinimumHeight(300)
                self._view_slot.addWidget(self._view, 1)

    def _chart_file(self) -> str:
        """The dock's one page file, rewritten in place for every render and
        removed with its folder on unload (:meth:`cleanup`)."""
        if self._tmp_dir is None or not os.path.isdir(self._tmp_dir):
            self._tmp_dir = tempfile.mkdtemp(prefix="o2viz_")
        return os.path.join(self._tmp_dir, CHART_FILE_NAME)

    def _show_html(self, html: str, status: str, embed_html: str | None = None,
                   page_kind: str = "chart") -> None:
        """Show a page. ``page_kind`` is "chart", "explore" or "guide".
        ``html`` is the real page — what Export HTML and Open in browser use.
        ``embed_html``, when given, is shown in the panel instead (the
        legacy-WebKit explainer for an engine the embedded view cannot run),
        without losing the real chart for export."""
        path = self._chart_file()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(html)
        self._last_path = path
        self._page_version += 1
        self._exportable = False
        if page_kind in ("chart", "explore"):
            self._last_html = html
            self._chart_current = True
            self._stale = False
        self._page_kind = "card" if embed_html is not None else page_kind

        self._ensure_view()
        self.bridge.bind(self.layer_combo.currentLayer()
                         if self.link_check.isChecked() and page_kind != "guide"
                         else None)
        if embed_html is not None and self._view is not None:
            embedded = show_html_text(self._view, embed_html)
        else:
            embedded = show_html_file(self._view_kind, self._view, path,
                                      version=self._page_version)
        self._embedded = bool(embedded and self._view is not None)
        self._sync_export_actions()
        if embedded:
            where = f" · {self._view_kind}"
            # bring the chart into view (it sits under the controls)
            QTimer.singleShot(0, self._scroll_to_view)
        else:
            where = " (no embedded web view in this QGIS build — opened in your browser)"
        self.set_status(status + where)

    def _scroll_to_view(self) -> None:
        """Scroll so the chart's top edge sits at the top of the panel (or as
        far as the content allows). Not ``ensureWidgetVisible``: a web view
        reports its page caret as the focus rectangle, which lands anywhere."""
        if self._view is None or self._cleaned or self.tabs.currentIndex() != 0:
            return  # never pull the user off the Diagrams / Labels tab
        content = self._scroll.widget()
        if content.layout() is not None:
            content.layout().activate()
        top = self._view.mapTo(content, QPoint(0, 0)).y()
        bar = self._scroll.verticalScrollBar()
        bar.setValue(max(0, min(bar.maximum(), top - 8)))

    def _mark_render_failed(self) -> None:
        """A render that did not produce a chart leaves the previous page in
        the panel, which no longer matches the controls: exports go off until
        a chart renders again (they used to save the old page as a success)."""
        self._chart_current = False
        self._sync_export_actions()

    def _export_block_reason(self, vector: bool) -> str:
        """Why an export is unavailable right now ('' when it is available).
        ``vector`` asks for SVG/PNG/PDF, which need the chart drawn in the
        panel by a page that answers ``o2vizExport``."""
        kind = self._page_kind
        if kind is None:
            return "Render a chart first."
        if kind == "guide":
            return "The panel shows the guide. Render a chart to export it."
        if not self._chart_current or not self._last_html:
            return "The last render failed. Fix the settings and render again."
        if not vector:
            return ""
        if kind == "card":
            return ("This engine's chart is not drawn in the panel (legacy web "
                    "view): use Open in browser and its download button, or "
                    "pick the ECharts engine under Advanced.")
        if not self._embedded:
            return ("No embedded web view in this QGIS build: export HTML and "
                    "save images from your browser.")
        if kind == "explore":
            return exports.EXPLORE_EXPORT
        if not self._exportable:
            return (exports.MISSING_EXPORT if self._page_ready_answered()
                    else "The chart is still loading.")
        return ""

    def _page_ready_answered(self) -> bool:
        return getattr(self, "_probe_version", -1) == self._page_version

    def _sync_export_actions(self) -> None:
        if not hasattr(self, "export_menu_btn"):
            return
        html_reason = self._export_block_reason(vector=False)
        vector_reason = self._export_block_reason(vector=True)
        self.export_btn.setEnabled(not html_reason)
        self.export_btn.setToolTip(html_reason or "Save the interactive chart page")
        for action, what in ((self.export_svg_btn, "the engine's own vector drawing"),
                             (self.export_png_btn, "an image at a size you pick"),
                             (self.export_pdf_btn, "a vector PDF from the SVG")):
            action.setEnabled(not vector_reason)
            action.setToolTip(vector_reason or f"Save {what}")
        can_open = (self._page_kind is not None and bool(self._last_path)
                    and os.path.isfile(self._last_path or ""))
        self.browser_btn.setEnabled(can_open)
        self.export_menu_btn.setEnabled(any(
            a.isEnabled() for a in (self.export_btn, self.export_svg_btn,
                                    self.export_png_btn, self.export_pdf_btn,
                                    self.browser_btn)))

    def _open_in_browser(self) -> None:
        """Escape hatch: show the current page in the system browser. Always
        works, even when the embedded QWebEngine view paints blank."""
        if not self._last_path or not os.path.exists(self._last_path):
            if not self._last_html:
                return
            self._show_html(self._last_html, "Reopened")  # rebuilds the page file
        import webbrowser
        webbrowser.open("file:///" + self._last_path.replace("\\", "/"))
        self.set_status("Opened the current page in your browser")

    def _render(self) -> None:
        engine = engines()[max(0, self.engine_combo.currentIndex())]
        if not self._ensure_engine_available(engine):
            return
        try:
            spec = self._build_spec()
            if spec is None:
                self._mark_render_failed()
                return
            if spec["type"] not in engine.supports:
                self.set_status(f"{engine.label} cannot draw {spec['type']} charts")
                self._mark_render_failed()
                return
            html = (engine.build_custom_html(spec, spec["custom_vl"])
                    if spec.get("custom_vl") and hasattr(engine, "build_custom_html")
                    else engine.build_html(spec))
        except Exception as exc:
            self.set_status(f"Chart failed: {exc}")
            self._mark_render_failed()
            return
        self._last_action = "render"
        self._last_engine = engine
        self._last_spec = spec
        self._watch_charted_layer(self.layer_combo.currentLayer())
        # what the chart left out, said plainly (rows without a number, the
        # matplotlib bar cap, a style without categories)
        engine_note = getattr(engine, "last_note", "") or ""
        colors_note = (getattr(self, "_rows_note", "") + getattr(self, "_layer_colors_note", "")
                       + (f" · {engine_note}" if engine_note else ""))
        self._ensure_view()
        if self._view_kind == "webkit" and not engine.webkit_ok:
            # legacy QtWebKit (no QtWebEngine in this QGIS) can't run Plotly's /
            # Vega's modern JS — they parse-fail and the panel stays blank. Show
            # an explainer there, but keep the real chart for export / browser.
            self._show_html(
                html,
                f"{engine.label}: use Export ▾ → Open in browser — the embedded "
                f"WebKit view can't run it (pick ECharts under Advanced for a "
                f"chart in the panel)",
                embed_html=_webkit_card(engine.label, spec.get("type", "")))
        else:
            scope = (f" · {self._last_extraction_info.status_note}"
                     if self._last_extraction_info is not None else "")
            self._show_html(
                html, f"Rendered {spec['type']} · {engine.label}"
                      f"{self._facet_note(spec, engine)}{scope}{colors_note}")
        self._save_last_setup()

    @staticmethod
    def _facet_note(spec: dict, engine) -> str:
        """Status fragment for small multiples: panel count, and which groups
        the panel cap left out — or why an engine drew one chart instead."""
        fac = spec.get("facets")
        if not fac:
            return ""
        if spec["type"] not in engine.facets:
            return f" · {engine.label} has no small multiples: one chart of all rows"
        note = f" · {len(fac['labels'])} panels by {fac['field']}"
        dropped = fac.get("dropped") or []
        if dropped:
            shown = ", ".join(str(v) for v in dropped[:5])
            more = "…" if len(dropped) > 5 else ""
            note += f" ({len(dropped)} smaller groups left out: {shown}{more})"
        return note

    # ───────────────────────── advanced engine availability ─────────────────────────

    def _refresh_engine_labels(self) -> None:
        for i in range(self.engine_combo.count()):
            eng = engines()[i]
            label = eng.label if eng.available() else f"{eng.label}  (install…)"
            self.engine_combo.setItemText(i, label)

    def _ensure_engine_available(self, engine) -> bool:
        """If an optional engine's libraries are missing, tell the user exactly
        how to install them themselves. The studio never runs pip (it must not
        shell out to a package manager); it only shows the copy-pasteable
        command. Returns True when the engine is ready to render."""
        if engine.available():
            return True
        pkgs = requirements.ENGINE_PIP_REQUIREMENTS.get(engine.id, [])
        missing = requirements.missing_packages(pkgs)
        if not missing:
            return True
        cmd = requirements.install_command_str(missing)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Advanced engine needs a library")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"<b>{engine.label}</b> needs: {', '.join(missing)}.<br><br>"
            "Install it into the QGIS Python yourself, then reopen the dock — "
            "run this in the <b>OSGeo4W Shell</b> (or the QGIS Python console):"
            f"<br><br><code>{cmd}</code>")
        copy_btn = box.addButton("Copy command", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is copy_btn:
            with suppress(Exception):
                QApplication.clipboard().setText(cmd)
            self.set_status(f"Copied the install command for {', '.join(missing)}")
        else:
            self.set_status(f"{engine.label} needs {', '.join(missing)}")
        return False

    def _explore(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is None:
            self.set_status("Pick a layer first")
            return
        try:
            sections = {self.tile_picker.item(i).data(Qt.ItemDataRole.UserRole)
                         for i in range(self.tile_picker.count())
                         if self.tile_picker.item(i).checkState() == Qt.CheckState.Checked}
            prof = profiler.build_profile(
                layer, self.selected_only.isChecked(), self._current_theme(),
                sections=sections,
                animate_by=self.explore_animate_combo.currentField())
            if not prof["tiles"]:
                self.set_status("Nothing chartable found in this layer's fields")
                self._mark_render_failed()
                return
            html = build_dashboard(prof, self._current_theme())
        except Exception as exc:
            self.set_status(f"Explore failed: {exc}")
            self._mark_render_failed()
            return
        self._last_action = "explore"
        self._watch_charted_layer(layer)
        frames = prof.get("frames")
        played = (f", playing {len(frames['labels'])} frames of {frames['field']}"
                  if frames else "")
        self._show_html(html, f"Explored {layer.name()}: {len(prof['tiles'])} charts, "
                              f"{len(prof['insights'])} insights{played}",
                        page_kind="explore")

    # ───────────────────────── smart assistant ─────────────────────────

    def _suggest_chart(self) -> None:
        """Offline assistant: pick the most suitable chart for this layer, configure the
        controls and render it."""
        layer = self.layer_combo.currentLayer()
        if layer is None:
            self.set_status("Pick a layer first")
            return
        # Cheap layer metadata only — no feature iteration yet — so the
        # decision below (and the field cap it drives) happens BEFORE any
        # data is pulled. Reported crash: even with the O(fields^2)
        # correlation scan bounded (core/assistant.py), pulling EVERY field
        # of a wide grid/zonal-stats layer into Python for up to 100k rows
        # is itself heavy enough to strain memory — the scan cap alone
        # wasn't the whole story.
        all_fields = layer.fields()
        numeric_names = [f.name() for f in all_fields if f.isNumeric()]
        other_names = [f.name() for f in all_fields if not f.isNumeric()]
        row_estimate = (len(layer.selectedFeatureIds())
                        if self.selected_only.isChecked() else layer.featureCount())
        full = False
        if assistant.would_sample(len(numeric_names), row_estimate):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Suggest — large layer")
            box.setText(f"This layer has {len(numeric_names)} numeric "
                       f"field(s) and about {row_estimate:,} feature(s).")
            box.setInformativeText(
                "To stay responsive, Suggest normally checks a representative "
                "sample of the fields and rows for the strongest relationship "
                "— reliable for the recommendation, and instant. Scanning "
                "every field against every row on a layer this size can take "
                "a long time and use a lot of memory.")
            sample_btn = box.addButton("Use a sample (recommended)",
                                       QMessageBox.ButtonRole.AcceptRole)
            full_btn = box.addButton("Scan the full dataset",
                                     QMessageBox.ButtonRole.DestructiveRole)
            box.setDefaultButton(sample_btn)
            box.exec()
            full = box.clickedButton() is full_btn
        # Bound the raw pull itself regardless of the choice above — "full
        # scan" means "don't sub-sample the rows/fields we DID pull", not
        # "pull literally every field of a 1000-column layer"; that upper
        # bound (300) is generous enough to never matter on a real layer.
        field_cap = _SUGGEST_FULL_FIELD_CAP if full else _SUGGEST_FIELD_CAP
        names = numeric_names[:field_cap] + other_names[:20]
        try:
            cols, fids = datasource.columns_with_ids(
                layer, names, self.selected_only.isChecked())
        except Exception as exc:
            self.set_status(f"Suggest failed: {exc}")
            return
        sug = assistant.suggest_chart(cols, fids, full=full)
        if not sug:
            self.set_status("No clear chart suggestion — try ✨ Explore for an overview")
            return
        self._apply_chart_suggestion(sug)
        note = (" (based on a sample of the fields/rows — Suggest again and "
               "choose “Scan the full dataset” for an exhaustive search)"
               if sug.get("sampled") else "")
        self.set_status("💡 " + sug["why"] + note)
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
        self._show_html(html, "Opened the 02viz user guide", page_kind="guide")

    def _export_html(self) -> None:
        reason = self._export_block_reason(vector=False)
        if reason:
            self.set_status(reason)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export chart as HTML", os.path.join(self._last_io_dir(), "02viz_chart.html"), "HTML (*.html)")
        if not path:
            return
        path = ensure_extension(path, ".html")
        self._remember_io_dir(path)
        try:
            size = atomic_write_text(path, self._last_html)
            self.set_status(
                f"Exported HTML: {os.path.basename(path)} · {human_size(size)}")
        except Exception as exc:
            self.set_status(f"HTML export failed: {exc}")

    def _export_svg(self) -> None:
        self._export_rendered_dialog("SVG", ".svg", "SVG (*.svg)")

    def _export_png(self) -> None:
        self._export_rendered_dialog("PNG", ".png", "PNG (*.png)")

    def _export_pdf(self) -> None:
        self._export_rendered_dialog("PDF", ".pdf", "PDF (*.pdf)")

    def _png_default_size(self) -> tuple[int, int]:
        raw = QSettings().value(PNG_SIZE_KEY, "")
        match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", raw if isinstance(raw, str) else "")
        if match:
            return int(match.group(1)), int(match.group(2))
        width, height = self._view_css_size()
        return max(1200, width * 2), max(800, height * 2)

    def _ask_png_size(self):
        """The PNG size dialog (a method so a test can answer it)."""
        return exports.ask_png_size(self, *self._png_default_size())

    def _view_css_size(self) -> tuple[int, int]:
        """The chart's size as the panel shows it, in CSS pixels; SVG and PDF
        are drawn at this size so text keeps the proportions on screen."""
        if self._view is None:
            return 960, 600
        return max(320, self._view.width()), max(240, self._view.height())

    def _export_rendered_dialog(self, output_format: str, extension: str,
                                file_filter: str) -> None:
        reason = self._export_block_reason(vector=True)
        if reason:
            self.set_status(f"{output_format} export unavailable: {reason}")
            return
        size = None
        if output_format == "PNG":
            size = self._ask_png_size()
            if size is None:
                return
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export chart as {output_format}",
            os.path.join(self._last_io_dir(), f"02viz_chart{extension}"),
            file_filter,
        )
        if not path:
            return
        path = ensure_extension(path, extension)
        self._remember_io_dir(path)
        self.set_status(f"Exporting {output_format}…")
        # the page answers through a nested event loop: no second export from
        # the menu meanwhile
        self.export_menu_btn.setEnabled(False)
        try:
            written = self._export_view_to(path, output_format, *(size or ()))
        except Exception as exc:
            self.set_status(f"{output_format} export failed: {exc}")
            return
        finally:
            with contextlib.suppress(RuntimeError):
                self._sync_export_actions()
        dims = f" · {size[0]} × {size[1]} px" if size else ""
        if size:
            QSettings().setValue(PNG_SIZE_KEY, f"{size[0]}x{size[1]}")
        self.set_status(f"Exported {output_format}: {os.path.basename(path)} · "
                        f"{human_size(written)}{dims}")

    def _export_view_to(self, path: str, output_format: str,
                        width: int | None = None, height: int | None = None) -> int:
        """Write the chart shown in the panel as SVG, PNG or PDF.

        The page draws the export itself (``window.o2vizExport``): SVG is the
        engine's vector output, PNG is drawn again at ``width`` × ``height``
        CSS pixels, PDF is drawn here from that SVG (vector). Raises
        ``ValueError`` with a plain reason when the panel shows anything but a
        rendered chart. Returns the written size in bytes."""
        fmt = output_format.upper()
        if fmt not in {"PNG", "SVG", "PDF"}:
            raise ValueError(f"Unsupported rendered export format: {fmt}")
        reason = self._export_block_reason(vector=True)
        if reason:
            raise ValueError(reason)
        if not (width and height):
            width, height = self._view_css_size()
        engine = getattr(self, "_last_engine", None)
        if (self._page_kind == "chart" and engine is not None
                and hasattr(engine, "render") and getattr(self, "_last_spec", None)):
            # matplotlib: savefig output straight from Python, at the size
            return self._export_engine_render(engine, path, fmt, width, height)
        if fmt == "PNG":
            payload = exports.run_page_export(
                self._view_kind, self._view, "png", width, height)
            return exports.write_bytes(path, exports.png_bytes(payload))
        svg = exports.svg_text(exports.run_page_export(
            self._view_kind, self._view, "svg", width, height))
        if fmt == "SVG":
            return exports.write_svg(path, svg)
        return exports.svg_to_pdf(svg, path)

    def _export_engine_render(self, engine, path: str, fmt: str, width: int,
                              height: int) -> int:
        """Engines that draw in Python (matplotlib) export their own
        ``savefig`` output: PNG / SVG bytes at ``width`` × ``height``, PDF
        drawn from that SVG like the others."""
        if fmt == "PNG":
            data = engine.render(self._last_spec, "png", width, height)
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"{engine.label} did not return a PNG image.")
            return exports.write_bytes(path, data)
        svg = exports.svg_text(engine.render(self._last_spec, "svg", width, height)
                               .decode("utf-8"))
        if fmt == "SVG":
            return exports.write_svg(path, svg)
        return exports.svg_to_pdf(svg, path)

    def _on_page_download(self, download) -> None:
        """Save a file the page offers through its own toolbar (the ECharts /
        Plotly download buttons used to do nothing inside QGIS)."""
        name = download.suggested_name()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the chart's download",
            os.path.join(self._last_io_dir(), name), "All files (*.*)")
        if not path:
            download.cancel()
            self.set_status("Download cancelled")
            return
        ext = os.path.splitext(name)[1]
        if ext:
            path = ensure_extension(path, ext)
        self._remember_io_dir(path)
        label = os.path.basename(path)
        try:
            size = download.save_to(path)
        except Exception as exc:
            self.set_status(f"Could not save {label}: {exc}")
            return
        watch = getattr(download, "when_done", None)
        if not size and callable(watch) and watch(
                lambda ok, detail: self._page_download_settled(label, ok, detail)):
            # QtWebEngine writes the file after accept(): report it when done
            self.set_status(f"Saving {label}…")
            return
        self.set_status(f"Saved {label}" + (f" · {human_size(size)}" if size else ""))

    def _page_download_settled(self, label: str, ok: bool, detail: str) -> None:
        # the dock may be gone by the time the engine finishes writing
        with contextlib.suppress(RuntimeError):
            self.set_status(f"Saved {label}" if ok else f"Could not save {label}: {detail}")

    def cleanup(self) -> None:
        """Called by the plugin's unload: remember the setup, stop following
        layers, release the page and remove this dock's temporary folder."""
        if self._cleaned:
            return
        with suppress(RuntimeError):  # widgets already torn down
            self._save_last_setup()
        self._cleaned = True
        self._stale_timer.stop()
        with suppress(RuntimeError, TypeError):  # project already gone
            QgsProject.instance().layersAdded.disconnect(self._on_project_layers_added)
        self._watch_charted_layer(None)
        self._watch_layer(None)
        if self._detach_downloads is not None:
            with suppress(RuntimeError, TypeError):  # already disconnected
                self._detach_downloads()
            self._detach_downloads = None
        if self._view is not None:
            with suppress(RuntimeError):  # view already deleted
                self._view.stop()
                self._view.setHtml("")
        QApplication.processEvents()
        if self._tmp_dir and os.path.isdir(self._tmp_dir):
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
        self._tmp_dir = None
        self._last_path = None

    def set_status(self, text: str) -> None:
        self.status.setText(text)
