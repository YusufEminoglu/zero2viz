# -*- coding: utf-8 -*-
"""Studio dock on a real QGIS runtime: layout at 350 x 572, pinned actions,
folded advanced rows, readable checkboxes and text, the last setup restored,
one temporary page per dock, stale charts redrawn after layer edits, and
chart colours taken from the layer's style (development set v0.20: A, E, F, G).

Run from the plugins root (the directory that contains ``zero2viz``)::

    python-qgis-ltr.bat -m zero2viz.tests.test_dock_layout_qgis   # QGIS 3 LTR
    python-qgis.bat     -m zero2viz.tests.test_dock_layout_qgis   # QGIS 4

QtWebEngine does not start in a ``python-qgis*.bat`` session, so the chart
view is the QtWebKit fallback where the runtime has it (QGIS 3) and the
"no embedded view" path elsewhere (QGIS 4); checks that need a drawn chart
say so when they skip.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import unittest
import webbrowser
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt" and os.environ.get("WINDIR"):
    # the Windows offscreen platform has no font engine of its own (TRAPS 4.3);
    # QtWebKit faults while laying out text without it
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ["WINDIR"], "Fonts"))

_SETTINGS_DIR = tempfile.TemporaryDirectory(prefix="zero2viz-layout-settings-")

from qgis.PyQt.QtCore import QPoint, QSettings  # noqa: E402

# never the developer's registry or live profile: every QSettings() the dock
# makes lands in this throwaway folder
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, _SETTINGS_DIR.name)

from qgis.core import (  # noqa: E402
    QgsApplication, QgsCategorizedSymbolRenderer, QgsFeature, QgsMarkerSymbol,
    QgsProject, QgsRendererCategory, QgsRuleBasedRenderer, QgsVectorLayer,
)
from qgis.PyQt.QtGui import QColor  # noqa: E402
from qgis.PyQt.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QLabel, QMainWindow, QPushButton, QStyle,
    QStyleFactory, QStyleOptionButton,
)

_APP = QgsApplication.instance()
if _APP is None:
    _APP = QgsApplication([], True, _SETTINGS_DIR.name, "external")
    _APP.initQgis()
if os.name == "nt":
    # the UI font QGIS uses on Windows; the offscreen default (Helvetica 12)
    # would measure a layout no user ever sees
    from qgis.PyQt.QtGui import QFont  # noqa: E402

    QgsApplication.setFont(QFont("Segoe UI", 9))

from zero2viz.dialogs import dock as dock_mod  # noqa: E402
from zero2viz.engines import engines  # noqa: E402

BROWSER_OPENS: list = []
webbrowser.open = lambda url, *a, **k: BROWSER_OPENS.append(url) or True


def _test_view(parent=None):
    """QtWebKit where the runtime ships it; otherwise no embedded view."""
    try:
        from qgis.PyQt.QtWebKitWidgets import QWebView
    except ImportError:
        return "browser", None
    return "webkit", QWebView(parent)


dock_mod.create_chart_view = _test_view
ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "icons"))
DOCK_SOURCE = os.path.join(os.path.dirname(dock_mod.__file__), "dock.py")
LAST_SETUP_KEY = "zero2viz/last_setup"


def spin(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        QgsApplication.processEvents()
        time.sleep(0.01)


def wait_for(predicate, seconds: float = 15.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        QgsApplication.processEvents()
        time.sleep(0.01)
    return predicate()


def luminance(color: QColor) -> float:
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(color.red()) + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue()))


def contrast(a: QColor, b: QColor) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def make_layer(name="districts", rows=12):
    layer = QgsVectorLayer(
        "Point?crs=EPSG:4326&field=name:string&field=use:string&field=pop:integer",
        name, "memory")
    feats = []
    for i in range(rows):
        f = QgsFeature(layer.fields())
        f.setAttributes([f"d{i}", ("housing", "retail", "park")[i % 3], 1000 + 100 * i])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    QgsProject.instance().addMapLayer(layer)
    return layer


class DockCase(unittest.TestCase):
    def setUp(self):
        QSettings().remove(LAST_SETUP_KEY)
        BROWSER_OPENS.clear()
        self.window = QMainWindow()
        self.iface = MagicMock()
        self.iface.mainWindow.return_value = self.window
        self.layer = make_layer()
        self.docks = []
        self.dock = self.new_dock()

    def new_dock(self):
        dock = dock_mod.StudioDockWidget(self.iface, ICON_DIR, self.window)
        dock.setFloating(True)
        dock.resize(350, 572)
        dock.show()
        spin(0.3)
        self.docks.append(dock)
        return dock

    def tearDown(self):
        for dock in self.docks:
            dock.cleanup()
            dock.hide()
            dock.setParent(None)
            dock.deleteLater()
        self.docks.clear()
        QgsProject.instance().removeAllMapLayers()
        self.window.close()
        QgsApplication.sendPostedEvents()
        spin(0.1)

    def render_bar(self, dock):
        ids = [e.id for e in engines()]
        dock.layer_combo.setLayer(self.layer)
        dock.engine_combo.setCurrentIndex(ids.index("echarts"))
        dock.type_combo.setCurrentIndex(dock.type_combo.findData("bar"))
        dock.x_combo.setField("use")
        dock.agg_combo.setCurrentIndex(dock.agg_combo.findText("count"))
        loads = []
        dock._ensure_view()
        if dock._view is not None:
            dock._view.loadFinished.connect(loads.append)
        dock._render()
        if dock._view is not None:
            self.assertTrue(wait_for(lambda: loads, 20), "the chart page never loaded")
            spin(0.5)
        return loads


class LayoutAt350(DockCase):
    def assert_no_horizontal_scroll(self, dock, where):
        spin(0.2)
        scroll = dock._scroll
        bar = scroll.horizontalScrollBar()
        need = scroll.widget().minimumSizeHint().width()
        self.assertEqual(bar.maximum(), 0, f"{where}: horizontal scroll range {bar.maximum()}"
                                           f" (content needs {need} px, viewport "
                                           f"{scroll.viewport().width()} px)")
        self.assertLessEqual(need, scroll.viewport().width(), where)

    def test_no_horizontal_scroll_on_any_tab_or_fold(self):
        dock = self.dock
        self.assertEqual((dock.width(), dock.height()), (350, 572))
        dock.layer_combo.setLayer(self.layer)
        for index in range(dock.tabs.count()):
            dock.tabs.setCurrentIndex(index)
            self.assert_no_horizontal_scroll(dock, f"tab {index}")
        dock.tabs.setCurrentIndex(0)
        dock.advanced_fold.set_open(True)
        dock.explore_fold.set_open(True)
        dock.custom_spec_check.setEnabled(True)
        self.assert_no_horizontal_scroll(dock, "Advanced and Explore options open")
        long_status = ("Plotly: use Export ▾ → Open in browser — the embedded WebKit view "
                       "can't run it (pick ECharts under Advanced for a chart in the panel)")
        dock.set_status(long_status)
        spin(0.2)
        self.assertLessEqual(dock.widget().minimumSizeHint().width(), 350)

    def test_render_export_and_status_are_pinned_below_the_scroll_area(self):
        dock = self.dock
        content = dock._scroll.widget()
        scroll_bottom = dock._scroll.mapTo(dock, QPoint(0, dock._scroll.height())).y()
        for widget in (dock.render_btn, dock.export_menu_btn, dock.status):
            self.assertFalse(content.isAncestorOf(widget), widget.objectName())
            top = widget.mapTo(dock, QPoint(0, 0)).y()
            self.assertGreaterEqual(top, scroll_bottom - 1)
            self.assertLessEqual(top + widget.height(), dock.height())
            self.assertTrue(widget.isVisible())
        # Diagrams / Labels swap in their own pinned Apply / Clear
        dock.tabs.setCurrentIndex(2)
        spin(0.1)
        texts = [b.text() for b in dock.action_stack.currentWidget().findChildren(QPushButton)]
        self.assertEqual(texts, ["Apply to layer", "Clear"])
        self.assertFalse(dock.render_btn.isVisible())

    def test_exports_live_in_one_menu(self):
        dock = self.dock
        names = [a.text() for a in dock.export_menu.actions() if not a.isSeparator()]
        for word in ("HTML", "SVG", "PNG", "PDF", "browser"):
            self.assertTrue(any(word in n for n in names), (word, names))
        stray = [b.text() for b in dock.findChildren(QPushButton)
                 if b.text().startswith("Export") or b.text() == "↗"]
        self.assertEqual(stray, [])

    def test_first_screen_leads_with_layer_and_fields_engine_is_folded(self):
        dock = self.dock
        self.assertFalse(dock.advanced_fold.is_open())
        self.assertFalse(dock.engine_combo.isVisibleTo(dock))
        self.assertTrue(dock.advanced_fold.body.isAncestorOf(dock.engine_combo))
        content = dock._scroll.widget()
        viewport_h = dock._scroll.viewport().height()
        self.assertEqual(dock._scroll.verticalScrollBar().value(), 0)
        tops = []
        for widget in (dock.layer_combo, dock.type_combo, dock.x_combo, dock.y_combo):
            top = widget.mapTo(content, QPoint(0, 0)).y()
            self.assertTrue(widget.isVisible())
            self.assertLessEqual(top + widget.height(), viewport_h, widget)
            tops.append(top)
        self.assertEqual(tops, sorted(tops))
        dock.advanced_fold.set_open(True)
        spin(0.1)
        self.assertTrue(dock.engine_combo.isVisible())

    def test_view_scrolls_to_the_chart_after_rendering(self):
        dock = self.dock
        self.render_bar(dock)
        if dock._view is None:
            self.assertTrue(BROWSER_OPENS, "no view: the chart must open in the browser")
            print("  note: no embedded web view in this runtime, scroll check skipped")
            return
        spin(0.3)
        bar = dock._scroll.verticalScrollBar()
        top = dock._view.mapTo(dock._scroll.widget(), QPoint(0, 0)).y() - bar.value()
        self.assertGreater(bar.value(), 0)
        self.assertGreaterEqual(top, 0)
        self.assertLess(top, dock._scroll.viewport().height())


class ReadableControls(DockCase):
    def indicator_pixels(self, box: QCheckBox):
        """The indicator's fill (just inside its border, clear of a check
        mark) and the pixels along its top edge."""
        option = QStyleOptionButton()
        box.initStyleOption(option)
        rect = box.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, box)
        image = box.grab().toImage()
        fill = QColor(image.pixel(rect.left() + 3, rect.top() + 3))
        edge = [QColor(image.pixel(x, y)) for x in range(rect.left(), rect.right() + 1)
                for y in (rect.top(), rect.top() + 1)]
        return rect, fill, edge

    def check_indicators(self, where):
        box = self.dock.selected_only
        box.setChecked(False)
        spin(0.1)
        rect, off_fill, edge = self.indicator_pixels(box)
        self.assertGreaterEqual(rect.width(), 10, where)
        self.assertGreater(luminance(off_fill), 0.85,
                           f"{where}: unchecked box is not light ({off_fill.name()})")
        self.assertTrue(any(contrast(c, QColor("#ffffff")) >= 3.0 for c in edge),
                        f"{where}: unchecked box has no visible border")
        box.setChecked(True)
        spin(0.1)
        _rect, on_fill, _edge = self.indicator_pixels(box)
        box.setChecked(False)
        self.assertGreater(contrast(on_fill, off_fill), 3.0,
                           f"{where}: ticked ({on_fill.name()}) and unticked "
                           f"({off_fill.name()}) boxes look alike")

    def test_checkbox_indicators_visible_under_styles_and_themes(self):
        original = QApplication.style().objectName()
        try:
            for style in ("Fusion", "Windows"):
                QApplication.setStyle(QStyleFactory.create(style))
                spin(0.2)
                self.check_indicators(style)
            QApplication.setStyle(QStyleFactory.create("Fusion"))
            for theme in ("Night Mapping", "Blend of Gray"):
                QgsApplication.setUITheme(theme)
                spin(0.3)
                self.check_indicators(theme)
        finally:
            QgsApplication.setUITheme("default")
            QApplication.setStyle(QStyleFactory.create(original or "Fusion"))
            spin(0.2)

    def test_no_background_or_border_on_the_checkbox_itself(self):
        blocks = re.findall(r"(?m)^\s*QCheckBox\s*\{([^}]*)\}", dock_mod._DOCK_QSS)
        self.assertTrue(blocks)
        for body in blocks:
            self.assertNotRegex(body, r"background|border")

    def test_primary_buttons_and_placeholders_reach_4_5_to_1(self):
        self.assertGreaterEqual(contrast(QColor(dock_mod._ACCENT), QColor("#ffffff")), 4.5)
        self.assertGreaterEqual(contrast(QColor(dock_mod._MUTED_TEXT), QColor("#ffffff")), 4.5)
        self.assertIn(dock_mod._ACCENT, dock_mod._RENDER_CHART_BTN_QSS)
        self.assertNotIn("#2a8f85", dock_mod._RENDER_CHART_BTN_QSS + dock_mod._RENDER_BTN_QSS)
        # measured: the darkest pixel of the rendered placeholder text
        edit = self.dock.title_edit
        edit.clear()
        spin(0.1)
        image = edit.grab().toImage()
        area = edit.contentsRect().adjusted(4, 3, -4, -3)
        darkest = min((QColor(image.pixel(x, y)) for x in range(area.left(), area.right())
                       for y in range(area.top(), area.bottom())), key=luminance)
        self.assertGreaterEqual(contrast(darkest, QColor("#ffffff")), 4.5,
                                f"placeholder text {darkest.name()}")

    def test_no_garbled_or_empty_labels(self):
        with open(DOCK_SOURCE, encoding="utf-8") as handle:
            self.assertNotIn("Â", handle.read())
        texts = [w.text() for w in self.dock.findChildren(QLabel)]
        self.assertNotIn("Spec JSON", texts)
        dock = self.dock
        dock.layer_combo.setLayer(self.layer)
        dock._preset_library["p"] = {"schema": 1, "engine": "echarts", "type": "bar",
                                     "fields": {"x": "gone_field"}}
        dock._refresh_preset_combo("p")
        dock._load_selected_preset()
        self.assertEqual(dock.status.text(),
                         'Loaded chart preset "p" · missing fields cleared: gone_field')


class PanelState(DockCase):
    def test_first_layer_added_with_the_panel_open_fills_the_field_lists(self):
        # QGIS 4 selects the first layer of an empty project in the combo but
        # signals layerChanged(None): the field lists stayed empty
        QgsProject.instance().removeAllMapLayers()
        dock = self.new_dock()
        layer = make_layer("first")
        spin(0.2)
        self.assertIs(dock.layer_combo.currentLayer(), layer)
        self.assertIs(dock.x_combo.layer(), layer)
        dock.x_combo.setField("use")
        self.assertEqual(dock.x_combo.currentField(), "use")

    def test_last_setup_is_restored_on_reopen(self):
        dock = self.dock
        ids = [e.id for e in engines()]
        dock.layer_combo.setLayer(self.layer)
        dock.engine_combo.setCurrentIndex(ids.index("plotly"))
        dock.type_combo.setCurrentIndex(dock.type_combo.findData("scatter"))
        dock.theme_combo.setCurrentText("Ink Dark")
        dock.x_combo.setField("pop")
        dock.y_combo.setField("pop")
        dock.title_edit.setText("Population")
        dock.layer_colors_check.setChecked(True)
        dock.advanced_fold.set_open(True)
        dock.cleanup()
        other = make_layer("other")
        again = self.new_dock()
        self.assertEqual(again.layer_combo.currentLayer().id(), self.layer.id())
        self.assertNotEqual(again.layer_combo.currentLayer().id(), other.id())
        self.assertEqual(again.engine_combo.currentData(), "plotly")
        self.assertEqual(again.type_combo.currentData(), "scatter")
        self.assertEqual(again.theme_combo.currentText(), "Ink Dark")
        self.assertEqual((again.x_combo.currentField(), again.y_combo.currentField()),
                         ("pop", "pop"))
        self.assertEqual(again.title_edit.text(), "Population")
        self.assertTrue(again.layer_colors_check.isChecked())
        self.assertTrue(again.advanced_fold.is_open())

    def test_one_temporary_page_per_dock_removed_on_cleanup(self):
        dock = self.dock
        self.render_bar(dock)
        dock.type_combo.setCurrentIndex(dock.type_combo.findData("pie"))
        dock._render()
        spin(0.5)
        dock._open_guide()
        spin(0.5)
        folder = dock._tmp_dir
        self.assertTrue(folder and os.path.isdir(folder))
        self.assertEqual(os.listdir(folder), [dock_mod.CHART_FILE_NAME])
        dock.cleanup()
        self.assertFalse(os.path.exists(folder))

    def test_edit_and_commit_mark_the_chart_stale_and_redraw_it(self):
        dock = self.dock
        self.render_bar(dock)
        self.assertIn("Rendered bar", dock.status.text())
        before = dock._last_html
        redraws = []
        original = dock._render
        dock._render = lambda: (redraws.append(1), original())
        layer = self.layer
        self.assertTrue(layer.startEditing())
        idx = layer.fields().indexOf("use")
        for fid in [f.id() for f in layer.getFeatures()][:4]:
            layer.changeAttributeValue(fid, idx, "industry")
        self.assertTrue(dock._stale)
        self.assertIsNone(dock.bridge._layer_id, "stale ids must not select features")
        self.assertTrue(layer.commitChanges())
        self.assertTrue(wait_for(lambda: redraws and not dock._stale, 5))
        spin(0.3)
        self.assertEqual(len(redraws), 1, "edits in one burst redraw once")
        self.assertNotEqual(dock._last_html, before)
        self.assertIn('"industry"', dock._last_html)
        self.assertIn("Rendered bar", dock.status.text())


class ChartOptions(DockCase):
    def test_horizontal_reverse_and_race_reach_the_spec(self):
        dock = self.dock
        dock.layer_combo.setLayer(self.layer)
        dock.type_combo.setCurrentIndex(dock.type_combo.findData("bar"))
        dock.x_combo.setField("use")
        dock.agg_combo.setCurrentIndex(dock.agg_combo.findText("count"))
        self.assertNotIn("options", dock._build_spec())
        self.assertTrue(dock.horizontal_check.isEnabled())
        dock.horizontal_check.setChecked(True)
        dock.reverse_x_check.setChecked(True)
        dock.reverse_y_check.setChecked(True)
        self.assertEqual(dock._build_spec()["options"],
                         {"horizontal": True, "reverse_x": True, "reverse_y": True})
        dock.type_combo.setCurrentIndex(dock.type_combo.findData("scatter"))
        self.assertFalse(dock.horizontal_check.isEnabled())
        dock.type_combo.setCurrentIndex(dock.type_combo.findData("bar"))
        self.assertFalse(dock.race_check.isEnabled())
        dock.horizontal_check.setChecked(False)
        dock.reverse_x_check.setChecked(False)
        dock.reverse_y_check.setChecked(False)
        dock.x_combo.setField("name")
        dock.y_combo.setField("pop")
        dock.agg_combo.setCurrentIndex(dock.agg_combo.findText("sum"))
        dock.animate_combo.setField("use")
        self.assertTrue(dock.race_check.isEnabled())
        self.assertEqual(dock._build_spec()["options"], {"race": True})
        dock.race_check.setChecked(False)
        self.assertEqual(dock._build_spec()["options"], {"race": False})

    def test_aggregate_none_leaves_null_values_out(self):
        layer = QgsVectorLayer("None?field=name:string&field=pop:integer", "gaps", "memory")
        feats = []
        for name, pop in (("A", 5), ("B", None), ("C", 7), ("A", 9)):
            f = QgsFeature(layer.fields())
            f.setAttributes([name, pop])
            feats.append(f)
        layer.dataProvider().addFeatures(feats)
        QgsProject.instance().addMapLayer(layer)
        dock = self.dock
        dock.layer_combo.setLayer(layer)
        dock.type_combo.setCurrentIndex(dock.type_combo.findData("bar"))
        dock.x_combo.setField("name")
        dock.y_combo.setField("pop")
        dock.agg_combo.setCurrentIndex(dock.agg_combo.findText("none"))
        data = dock._build_spec()["data"]
        self.assertEqual(data["categories"], ["A", "C", "A (2)"])
        self.assertEqual(data["series"][0]["values"], [5.0, 7.0, 9.0])
        self.assertIn("1 row without a number in pop left out", dock._rows_note)

    def test_title_bridge_selects_only_on_the_plugin_message_shape(self):
        bridge = self.dock.bridge
        bridge.bind(self.layer)
        fids = sorted(f.id() for f in self.layer.getFeatures())
        for title in ("o2viz-select:%d,%d" % (fids[0], fids[1]),       # no sequence
                      "o2viz-select:<img src=x>:1",                      # crafted
                      "o2viz-select:%d;alert(1):2" % fids[0],
                      "districts o2viz-select:%d:3" % fids[0]):
            bridge.handle_title(title)
            self.assertEqual(self.layer.selectedFeatureCount(), 0, title)
        bridge.handle_title("o2viz-select:%d,%d:4" % (fids[0], fids[2]))
        self.assertEqual(sorted(self.layer.selectedFeatureIds()), [fids[0], fids[2]])


class LayerColours(DockCase):
    def spec_for(self, layer):
        dock = self.dock
        dock.layer_combo.setLayer(layer)
        dock.type_combo.setCurrentIndex(dock.type_combo.findData("bar"))
        dock.x_combo.setField("use")
        dock.agg_combo.setCurrentIndex(dock.agg_combo.findText("count"))
        dock.layer_colors_check.setChecked(True)
        return dock._build_spec()

    def test_categorized_style_colours_the_categories(self):
        categories = []
        for value, color in (("housing", "#d7301f"), ("retail", "#2b8cbe")):
            symbol = QgsMarkerSymbol.createSimple({"color": color})
            categories.append(QgsRendererCategory(value, symbol, value.title()))
        self.layer.setRenderer(QgsCategorizedSymbolRenderer("use", categories))
        spec = self.spec_for(self.layer)
        colors = spec["options"]["category_colors"]
        self.assertEqual(colors["housing"], "#d7301f")
        self.assertEqual(colors["retail"], "#2b8cbe")
        self.assertEqual(colors["Housing"], "#d7301f")
        self.assertNotIn("park", colors)

    def test_rule_based_style_colours_matching_categories(self):
        root = QgsRuleBasedRenderer.Rule(None)
        rule = QgsRuleBasedRenderer.Rule(
            QgsMarkerSymbol.createSimple({"color": "#31a354"}), 0, 0, "\"use\" = 'park'", "Parks")
        root.appendChild(rule)
        self.layer.setRenderer(QgsRuleBasedRenderer(root))
        spec = self.spec_for(self.layer)
        colors = spec["options"]["category_colors"]
        self.assertEqual(colors, {"park": "#31a354", "Parks": "#31a354"})

    def test_single_symbol_keeps_the_palette_and_says_why(self):
        spec = self.spec_for(self.layer)
        self.assertNotIn("options", spec)
        self.assertIn("layer colours not used", self.dock._layer_colors_note)


if __name__ == "__main__":
    print(f"QGIS {QgsApplication.instance().applicationVersion() if hasattr(QgsApplication, 'applicationVersion') else ''}"
          f" style={QApplication.style().objectName()}")
    result = unittest.main(exit=False, verbosity=2).result
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"  {total - failed}/{total} passed" + ("" if not failed else f"  FAIL ({failed})"))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.wasSuccessful() else 1)
