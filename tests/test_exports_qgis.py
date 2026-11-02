# -*- coding: utf-8 -*-
"""Rendered exports on the active QGIS runtime, from real chart pages.

SVG / PNG come from the page's own ``window.o2vizExport`` (an ECharts chart
rendered through the dock, plus a small page that implements the contract);
PDF is drawn from that SVG and must stay vector. Exports are off whenever
the panel shows anything but a rendered chart (the Guide, a failed render,
the legacy-WebKit explainer card, a page without the contract), and the
page's own toolbar downloads are saved where the user chooses.

QtWebEngine does not start in a ``python-qgis*.bat`` session, so the chart
view is QtWebKit where the runtime ships it (QGIS 3); QGIS 4 has no embedded
view here and checks the "no view" path, the SVG → PDF writer and the
download handler instead.

    python-qgis-ltr.bat -m zero2viz.tests.test_exports_qgis
    python-qgis.bat     -m zero2viz.tests.test_exports_qgis
"""
from __future__ import annotations

import os
import re
import struct
import sys
import tempfile
import time
import unittest
import webbrowser
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt" and os.environ.get("WINDIR"):
    # the Windows offscreen platform has no font engine (TRAPS 4.3); QtWebKit
    # faults laying out text without one
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ["WINDIR"], "Fonts"))

_SETTINGS_DIR = tempfile.TemporaryDirectory(prefix="zero2viz-export-settings-")

from qgis.PyQt.QtCore import QSettings  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, _SETTINGS_DIR.name)

from qgis.core import (  # noqa: E402
    QgsApplication, QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer,
)
from qgis.PyQt.QtWidgets import QFileDialog, QMainWindow  # noqa: E402

_APP = QgsApplication.instance()
if _APP is None:
    _APP = QgsApplication([], True, _SETTINGS_DIR.name, "external")
    _APP.initQgis()
if os.name == "nt":
    from qgis.PyQt.QtGui import QFont  # noqa: E402

    QgsApplication.setFont(QFont("Segoe UI", 9))

from zero2viz.dialogs import dock as dock_mod  # noqa: E402
from zero2viz.dialogs import exports  # noqa: E402
from zero2viz.engines import engines  # noqa: E402

BROWSER_OPENS: list = []
webbrowser.open = lambda url, *a, **k: BROWSER_OPENS.append(url) or True
SAVE_TO = {"path": ""}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (SAVE_TO["path"], ""))


def _test_view(parent=None):
    try:
        from qgis.PyQt.QtWebKitWidgets import QWebView
    except ImportError:
        return "browser", None
    return "webkit", QWebView(parent)


dock_mod.create_chart_view = _test_view
HAS_VIEW = _test_view()[0] == "webkit"
ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "icons"))

# a page that implements the export contract and nothing else
CONTRACT_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>contract</title>
</head><body style="margin:0"><div id="chart"></div><script>
window.o2vizExport = function (format, width, height) {
  return new Promise(function (resolve, reject) {
    if (format === "svg") {
      resolve('<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' +
              height + '" viewBox="0 0 ' + width + ' ' + height + '">' +
              '<rect x="10" y="10" width="' + (width / 2) + '" height="' + (height / 2) +
              '" fill="#237a72"/><path d="M0 0 L' + width + ' ' + height +
              '" stroke="#16323f" stroke-width="3"/>' +
              '<text x="20" y="40" font-size="20" fill="#16323f">Izmir 2026</text></svg>');
    } else if (format === "png") {
      var c = document.createElement("canvas");
      c.width = width; c.height = height;
      var g = c.getContext("2d");
      g.fillStyle = "#237a72"; g.fillRect(0, 0, width, height);
      resolve(c.toDataURL("image/png"));
    } else { reject(new Error("unknown format " + format)); }
  });
};
window.__chartReady = true;
</script></body></html>"""

NO_CONTRACT_PAGE = ("<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
                    "<body><p>an old chart page</p><script>window.__chartReady = true;"
                    "</script></body></html>")


def spin(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        QgsApplication.processEvents()
        time.sleep(0.01)


def wait_for(predicate, seconds: float = 20.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        QgsApplication.processEvents()
        time.sleep(0.01)
    return bool(predicate())


def png_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as handle:
        head = handle.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("not a PNG file")
    return struct.unpack(">II", head[16:24])


def pdf_facts(path: str) -> dict:
    with open(path, "rb") as handle:
        raw = handle.read()
    box = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", raw)
    return {"pdf": raw[:4] == b"%PDF", "images": raw.count(b"/Subtype /Image"),
            "font": b"/Font" in raw,
            "media": (float(box.group(1)), float(box.group(2))) if box else None}


class ExportCase(unittest.TestCase):
    def setUp(self):
        QSettings().remove("zero2viz/last_setup")
        BROWSER_OPENS.clear()
        self.work = tempfile.TemporaryDirectory(prefix="zero2viz-export-")
        self.window = QMainWindow()
        self.iface = MagicMock()
        self.iface.mainWindow.return_value = self.window
        self.dock = dock_mod.StudioDockWidget(self.iface, ICON_DIR, self.window)
        self.dock.setFloating(True)
        self.dock.resize(480, 900)
        self.dock.show()
        self.layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=use:string&field=pop:integer", "rows", "memory")
        feats = []
        for i in range(12):
            f = QgsFeature(self.layer.fields())
            f.setAttributes([("housing", "retail", "park")[i % 3], 1000 + 100 * i])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(i, i)))
            feats.append(f)
        self.layer.dataProvider().addFeatures(feats)
        QgsProject.instance().addMapLayer(self.layer)
        self.loads: list = []
        spin(0.2)

    def tearDown(self):
        self.dock.cleanup()
        self.dock.hide()
        self.dock.setParent(None)
        self.dock.deleteLater()
        QgsProject.instance().removeAllMapLayers()
        self.window.close()
        QgsApplication.sendPostedEvents()
        spin(0.1)
        self.work.cleanup()

    def out(self, name: str) -> str:
        return os.path.join(self.work.name, name)

    def hook(self):
        self.dock._ensure_view()
        if self.dock._view is not None and not self.loads:
            self.dock._view.loadFinished.connect(self.loads.append)
            self.loads.append("hooked")

    def show_page(self, html: str, kind: str = "chart"):
        self.hook()
        before = len(self.loads)
        self.dock._show_html(html, "test page", page_kind=kind)
        if self.dock._view is not None:
            self.assertTrue(wait_for(lambda: len(self.loads) > before), "page never loaded")
            self.assertTrue(wait_for(lambda: self.dock._page_ready_answered(), 5))

    def render(self, engine_id="echarts", kind="bar"):
        ids = [e.id for e in engines()]
        dock = self.dock
        dock.layer_combo.setLayer(self.layer)
        dock.engine_combo.setCurrentIndex(ids.index(engine_id))
        dock.type_combo.setCurrentIndex(dock.type_combo.findData(kind))
        dock.x_combo.setField("use")
        dock.y_combo.setField("pop")
        dock.agg_combo.setCurrentIndex(dock.agg_combo.findText("sum"))
        self.hook()
        before = len(self.loads)
        dock._render()
        if dock._view is not None:
            self.assertTrue(wait_for(lambda: len(self.loads) > before), "chart never loaded")
            if dock._page_kind == "chart":
                self.assertTrue(wait_for(lambda: dock._page_ready_answered(), 5))
            spin(0.4)

    def vector_actions(self):
        d = self.dock
        return [d.export_svg_btn.isEnabled(), d.export_png_btn.isEnabled(),
                d.export_pdf_btn.isEnabled()]


@unittest.skipUnless(HAS_VIEW, "needs an embedded web view (QtWebKit) in this runtime")
class RealPageExports(ExportCase):
    def test_echarts_chart_exports_true_svg_sized_png_and_vector_pdf(self):
        self.render("echarts", "bar")
        self.assertEqual(self.vector_actions(), [True, True, True], self.dock.status.text())
        svg_path, png_path, pdf_path = self.out("c.svg"), self.out("c.png"), self.out("c.pdf")
        self.assertGreater(self.dock._export_view_to(svg_path, "SVG", 640, 400), 500)
        with open(svg_path, encoding="utf-8") as handle:
            svg = handle.read()
        self.assertIn("<svg", svg[:400])
        self.assertIn("<path", svg)
        self.assertIn("housing", svg)  # the axis labels are text, not pixels
        self.assertNotIn("<image", svg)
        self.dock._export_view_to(png_path, "PNG", 900, 500)
        self.assertEqual(png_size(png_path), (900, 500))
        self.dock._export_view_to(pdf_path, "PDF", 640, 400)
        facts = pdf_facts(pdf_path)
        self.assertTrue(facts["pdf"])
        self.assertEqual(facts["images"], 0, "the PDF must be vector, not a bitmap")
        self.assertTrue(facts["font"], "chart text must stay text in the PDF")
        self.assertAlmostEqual(facts["media"][0], 640 * 0.75, delta=1.0)
        self.assertAlmostEqual(facts["media"][1], 400 * 0.75, delta=1.0)

    def test_contract_page_round_trip_and_png_size_dialog(self):
        self.show_page(CONTRACT_PAGE)
        self.assertEqual(self.vector_actions(), [True, True, True])
        self.dock._export_view_to(self.out("k.svg"), "SVG", 500, 300)
        with open(self.out("k.svg"), encoding="utf-8") as handle:
            self.assertIn('width="500" height="300"', handle.read())
        # Export PNG asks for the size, then writes exactly that many pixels
        self.dock._ask_png_size = lambda: (640, 360)
        SAVE_TO["path"] = self.out("dialog.png")
        self.dock._export_png()
        self.assertEqual(png_size(self.out("dialog.png")), (640, 360))
        self.assertIn("640 × 360 px", self.dock.status.text())
        self.dock._ask_png_size = lambda: None  # cancelled: nothing written
        SAVE_TO["path"] = self.out("cancelled.png")
        self.dock._export_png()
        self.assertFalse(os.path.exists(self.out("cancelled.png")))
        SAVE_TO["path"] = self.out("k.pdf")
        self.dock._export_pdf()
        facts = pdf_facts(self.out("k.pdf"))
        self.assertEqual((facts["pdf"], facts["images"]), (True, 0), self.dock.status.text())

    def test_exports_off_for_guide_failed_render_and_webkit_card(self):
        self.render("echarts", "bar")
        self.assertTrue(all(self.vector_actions()))
        # the Guide: nothing to export, and Export HTML must not save the guide
        self.dock._open_guide()
        spin(0.6)
        self.assertEqual(self.vector_actions(), [False, False, False])
        self.assertFalse(self.dock.export_btn.isEnabled())
        with self.assertRaises(ValueError):
            self.dock._export_view_to(self.out("guide.png"), "PNG", 400, 300)
        # a failed render leaves the old chart in the panel: exports go off
        self.render("echarts", "bar")
        self.assertTrue(all(self.vector_actions()))
        self.dock.type_combo.setCurrentIndex(self.dock.type_combo.findData("histogram"))
        self.dock.x_combo.setField("use")  # text field: the histogram fails
        self.dock._render()
        self.assertEqual(self.vector_actions(), [False, False, False])
        self.assertFalse(self.dock.export_btn.isEnabled())
        SAVE_TO["path"] = self.out("stale.png")
        self.dock._ask_png_size = lambda: (400, 300)
        self.dock._export_png()
        self.assertFalse(os.path.exists(self.out("stale.png")))
        self.assertIn("unavailable", self.dock.status.text())
        # Plotly on legacy WebKit shows the explainer card: no image exports,
        # but the real chart is still there for HTML / the browser
        self.render("plotly", "bar")
        self.assertEqual(self.dock._page_kind, "card")
        self.assertEqual(self.vector_actions(), [False, False, False])
        self.assertTrue(self.dock.export_btn.isEnabled())
        self.assertTrue(self.dock.browser_btn.isEnabled())
        SAVE_TO["path"] = self.out("plotly.html")
        self.dock._export_html()
        with open(self.out("plotly.html"), encoding="utf-8") as handle:
            self.assertIn("Plotly", handle.read(200000))

    def test_page_without_the_contract_keeps_image_exports_off(self):
        self.show_page(NO_CONTRACT_PAGE)
        self.assertEqual(self.vector_actions(), [False, False, False])
        self.assertEqual(self.dock.export_svg_btn.toolTip(), exports.MISSING_EXPORT)
        with self.assertRaises(ValueError) as caught:
            self.dock._export_view_to(self.out("x.svg"), "SVG", 400, 300)
        self.assertEqual(str(caught.exception), exports.MISSING_EXPORT)

    def test_toolbar_download_is_saved_where_the_user_chooses(self):
        self.show_page(CONTRACT_PAGE)
        SAVE_TO["path"] = self.out("toolbar")
        self.dock._view.page().mainFrame().evaluateJavaScript(
            "var c=document.createElement('canvas');c.width=30;c.height=20;"
            "var a=document.createElement('a');a.download='02viz_chart.png';"
            "a.target='_blank';a.href=c.toDataURL('image/png');document.body.appendChild(a);"
            "a.dispatchEvent(new MouseEvent('click',{view:window,bubbles:true}));")
        self.assertTrue(wait_for(lambda: os.path.exists(self.out("toolbar.png")), 5),
                        self.dock.status.text())
        self.assertEqual(png_size(self.out("toolbar.png")), (30, 20))
        self.assertIn("Saved toolbar.png", self.dock.status.text())


def _matplotlib_ready() -> bool:
    return any(e.id == "matplotlib" and e.available() for e in engines())


@unittest.skipUnless(HAS_VIEW and _matplotlib_ready(),
                     "needs QtWebKit and matplotlib in this runtime")
class MatplotlibExports(ExportCase):
    def test_matplotlib_exports_its_own_savefig_output_at_the_size(self):
        self.render("matplotlib", "bar")
        self.assertEqual(self.dock._page_kind, "chart", self.dock.status.text())
        self.assertEqual(self.vector_actions(), [True, True, True], self.dock.status.text())
        self.dock._export_view_to(self.out("m.png"), "PNG", 800, 500)
        self.assertEqual(png_size(self.out("m.png")), (800, 500))
        self.dock._export_view_to(self.out("m.svg"), "SVG", 800, 500)
        with open(self.out("m.svg"), encoding="utf-8") as handle:
            svg = handle.read()
        self.assertIn("matplotlib", svg[:3000].lower())  # savefig's own metadata
        self.assertNotIn("<image", svg)
        self.dock._export_view_to(self.out("m.pdf"), "PDF", 800, 500)
        facts = pdf_facts(self.out("m.pdf"))
        self.assertEqual((facts["pdf"], facts["images"]), (True, 0))


class AnyRuntimeExports(ExportCase):
    def test_without_a_drawn_chart_image_exports_stay_off(self):
        self.assertEqual(self.vector_actions(), [False, False, False])
        self.assertFalse(self.dock.export_btn.isEnabled())
        self.assertFalse(self.dock.export_menu_btn.isEnabled())
        if HAS_VIEW:
            return
        self.render("echarts", "bar")  # no view: the chart opens in the browser
        self.assertTrue(BROWSER_OPENS, self.dock.status.text())
        self.assertEqual(self.vector_actions(), [False, False, False])
        self.assertTrue(self.dock.export_btn.isEnabled())
        self.assertIn("No embedded web view", self.dock.export_png_btn.toolTip())

    def test_svg_to_pdf_stays_vector_and_keeps_the_drawing_size(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500">'
               '<rect width="800" height="500" fill="#ffffff"/>'
               '<path d="M40 460 L760 40" stroke="#237a72" stroke-width="4"/>'
               '<text x="60" y="80" font-size="28" fill="#16323f">Izmir</text></svg>')
        path = self.out("v.pdf")
        self.assertGreater(exports.svg_to_pdf(svg, path), 300)
        facts = pdf_facts(path)
        self.assertEqual((facts["pdf"], facts["images"], facts["font"]), (True, 0, True))
        self.assertAlmostEqual(facts["media"][0], 600.0, delta=1.0)
        self.assertAlmostEqual(facts["media"][1], 375.0, delta=1.0)
        with self.assertRaises(ValueError):
            exports.svg_text("data:image/png;base64,iVBORw0KGgo=")
        with self.assertRaises(ValueError):
            exports.png_bytes("data:image/png;base64,AAAA")

    def test_engine_download_item_goes_where_the_user_chose(self):
        class Item:  # the slice of QWebEngineDownloadRequest the handler uses
            def __init__(self):
                self.calls = []

            def downloadFileName(self):  # noqa: N802
                return "02viz_chart.png"

            def setDownloadDirectory(self, folder):  # noqa: N802
                self.calls.append(("dir", folder))

            def setDownloadFileName(self, name):  # noqa: N802
                self.calls.append(("name", name))

            def accept(self):
                self.calls.append(("accept",))

            def cancel(self):
                self.calls.append(("cancel",))

        item = Item()
        SAVE_TO["path"] = self.out("from_toolbar")
        self.dock._on_page_download(exports.EngineDownload(item))
        self.assertEqual(item.calls, [("dir", os.path.abspath(self.work.name)),
                                      ("name", "from_toolbar.png"), ("accept",)])
        cancelled = Item()
        SAVE_TO["path"] = ""
        self.dock._on_page_download(exports.EngineDownload(cancelled))
        self.assertEqual(cancelled.calls, [("cancel",)])

    def test_engine_download_reports_only_when_written(self):
        # QtWebEngine writes the file after accept(): "Saved" must wait for
        # the item to finish, and a failed write must say so.
        from qgis.PyQt.QtCore import QObject, pyqtSignal

        class SignalItem(QObject):  # Qt 5 QWebEngineDownloadItem's shape
            finished = pyqtSignal()
            DownloadCompleted = 2
            DownloadInterrupted = 4

            def __init__(self, end_state):
                super().__init__()
                self.end_state = end_state
                self.current = 1

            def downloadFileName(self):  # noqa: N802
                return "02viz_chart.png"

            def setDownloadDirectory(self, folder):  # noqa: N802
                pass

            def setDownloadFileName(self, name):  # noqa: N802
                pass

            def accept(self):
                pass

            def cancel(self):
                pass

            def state(self):
                return self.current

            def interruptReasonString(self):  # noqa: N802
                return "Access denied"

            def finish(self):
                self.current = self.end_state
                self.finished.emit()

        for end_state, expected in ((SignalItem.DownloadCompleted, "Saved later.png"),
                                    (SignalItem.DownloadInterrupted,
                                     "Could not save later.png: Access denied")):
            item = SignalItem(end_state)
            SAVE_TO["path"] = self.out("later")
            self.dock._on_page_download(exports.EngineDownload(item))
            self.assertEqual(self.dock.status.text(), "Saving later.png…")
            item.finish()
            self.assertEqual(self.dock.status.text(), expected)

    def test_explore_dashboard_names_its_own_export_limit(self):
        self.dock._page_kind = "explore"
        self.dock._chart_current = True
        self.dock._last_html = "<html></html>"
        self.dock._embedded = True
        self.dock._exportable = False
        self.assertEqual(self.dock._export_block_reason(vector=True),
                         exports.EXPLORE_EXPORT)

    def test_bounded_extraction_reports_truncation(self):
        from zero2viz.core.datasource import columns_with_ids_info

        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=value:integer", "rows", "memory")
        features = []
        for value in range(5):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([value])
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(value, value)))
            features.append(feature)
        self.assertTrue(layer.dataProvider().addFeatures(features)[0])
        columns, fids, info = columns_with_ids_info(
            layer, ["value"], max_rows=3)
        self.assertEqual(columns["value"], [0, 1, 2])
        self.assertEqual(len(fids), 3)
        self.assertTrue(info.truncated)
        self.assertEqual(info.available_rows, 5)
        self.assertEqual(info.status_note, "first 3 of 5 rows")


if __name__ == "__main__":
    print(f"embedded view for the test: {'QtWebKit' if HAS_VIEW else 'none'}")
    result = unittest.main(exit=False, verbosity=2).result
    total = result.testsRun - len(result.skipped)
    failed = len(result.failures) + len(result.errors)
    print(f"  {total - failed}/{total} passed ({len(result.skipped)} skipped)"
          + ("" if not failed else f"  FAIL ({failed})"))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.wasSuccessful() else 1)
