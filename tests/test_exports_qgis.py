# -*- coding: utf-8 -*-
"""Real-Qt export verification on the active QGIS runtime."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer
from qgis.PyQt.QtWidgets import QLabel, QMainWindow


_APP = QgsApplication.instance()
if _APP is None:
    _APP = QgsApplication([], False)
    _APP.initQgis()

from zero2viz.dialogs.dock import StudioDockWidget  # noqa: E402


class TestRenderedExports(unittest.TestCase):

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="zero2viz-render-")
        self.window = QMainWindow()
        self.iface = MagicMock()
        self.iface.mainWindow.return_value = self.window
        self.iface.activeLayer.return_value = None
        icon_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "icons"))
        self.dock = StudioDockWidget(self.iface, icon_dir, self.window)
        self.view = QLabel("02viz publication export\nİzmir · 2026")
        self.view.setStyleSheet(
            "background:#ffffff;color:#16323f;font-size:24px;padding:30px;")
        self.view.resize(720, 420)
        self.view.show()
        QgsApplication.processEvents()
        self.dock._view = self.view

    def tearDown(self):
        self.dock._view = None
        self.view.close()
        self.dock.close()
        self.dock.setParent(None)
        self.window.close()
        QgsApplication.processEvents()
        self.work.cleanup()

    def test_png_svg_and_pdf_are_real_nonempty_files(self):
        outputs = {}
        for fmt, extension in (("PNG", ".png"), ("SVG", ".svg"), ("PDF", ".pdf")):
            path = os.path.join(self.work.name, f"chart{extension}")
            outputs[fmt] = path
            self.assertGreater(self.dock._export_view_to(path, fmt), 100)
            self.assertTrue(os.path.isfile(path))

        with open(outputs["PNG"], "rb") as handle:
            self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n")
        with open(outputs["SVG"], "rb") as handle:
            self.assertIn(b"<svg", handle.read(1024).lower())
        with open(outputs["PDF"], "rb") as handle:
            self.assertEqual(handle.read(4), b"%PDF")

    def test_render_buttons_are_initially_safe(self):
        self.assertFalse(self.dock.export_png_btn.isEnabled())
        self.assertFalse(self.dock.export_svg_btn.isEnabled())
        self.assertFalse(self.dock.export_pdf_btn.isEnabled())

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
    unittest.main()
