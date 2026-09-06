# -*- coding: utf-8 -*-
"""Pure-Python tests for reliable chart publishing helpers."""
from __future__ import annotations

import os
import tempfile
import unittest
import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "core" / "export_utils.py"
_SPEC = importlib.util.spec_from_file_location("zero2viz_export_utils", _MODULE_PATH)
export_utils = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(export_utils)
atomic_output = export_utils.atomic_output
atomic_write_text = export_utils.atomic_write_text
ensure_extension = export_utils.ensure_extension
human_size = export_utils.human_size


class TestExportUtils(unittest.TestCase):

    def setUp(self):
        scratch = Path(__file__).resolve().parent.parent / "scratch"
        descriptor, self.base = tempfile.mkstemp(
            prefix="zero2viz-core-", dir=scratch)
        os.close(descriptor)
        os.remove(self.base)

    def tearDown(self):
        folder = os.path.dirname(self.base)
        stem = os.path.basename(self.base)
        for name in os.listdir(folder):
            if name.startswith(stem):
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    continue

    def test_extension_is_case_insensitive(self):
        self.assertEqual(ensure_extension("chart", ".png"), "chart.png")
        self.assertEqual(ensure_extension("chart.PNG", ".png"), "chart.PNG")

    def test_atomic_text_publish_replaces_only_after_success(self):
        target = f"{self.base}.html"
        with open(target, "wb") as handle:
            handle.write(b"known-good")
        size = atomic_write_text(target, "<html>new chart</html>")
        self.assertEqual(size, len(b"<html>new chart</html>"))
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"<html>new chart</html>")

    def test_failed_writer_preserves_existing_chart(self):
        target = f"{self.base}.svg"
        with open(target, "wb") as handle:
            handle.write(b"known-good")
        with self.assertRaisesRegex(RuntimeError, "render failed"):
            with atomic_output(target) as temporary_path:
                with open(temporary_path, "wb") as handle:
                    handle.write(b"partial")
                raise RuntimeError("render failed")
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"known-good")
        self.assertFalse(any(
            name.startswith(".zero2viz-export-")
            for name in os.listdir(os.path.dirname(self.base))))

    def test_empty_output_is_rejected(self):
        target = f"{self.base}.pdf"
        with self.assertRaisesRegex(ValueError, "empty output"):
            with atomic_output(target) as temporary_path:
                open(temporary_path, "wb").close()
        self.assertFalse(os.path.exists(target))

    def test_human_size(self):
        self.assertEqual(human_size(500), "500 B")
        self.assertEqual(human_size(1536), "1.5 KB")


class TestOfflineEngines(unittest.TestCase):

    def test_all_vendored_engines_build_a_self_contained_bar_chart(self):
        from zero2viz.engines import engines

        spec = {
            "type": "bar",
            "title": "District population",
            "x_label": "district",
            "y_label": "population",
            "stacked": False,
            "theme": {
                "palette": ["#2a8f85", "#fa8e7a"],
                "bg": "#ffffff",
                "text": "#16323f",
                "grid": "#e3e7ec",
            },
            "data": {
                "categories": ["Konak", "Bornova"],
                "series": [{
                    "name": "population",
                    "values": [332_277, 452_479],
                    "ids": [[1], [2]],
                }],
            },
        }
        built = 0
        for engine in engines():
            if engine.id not in {"echarts", "plotly", "vegalite"}:
                continue
            html = engine.build_html(spec)
            self.assertTrue(html.startswith("<!DOCTYPE html>"), engine.id)
            self.assertIn("District population", html, engine.id)
            self.assertIn("Konak", html, engine.id)
            self.assertGreater(len(html), 10_000, engine.id)
            built += 1
        self.assertEqual(built, 3)


if __name__ == "__main__":
    unittest.main()
