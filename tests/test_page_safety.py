# -*- coding: utf-8 -*-
"""Pure tests: no title or data value can break out of a generated page, and
every engine page exposes ``window.o2vizExport`` (v0.20 set, items C and D).
Run with pytest from the plugin folder:
``py -3 -m pytest -o pythonpath=.. tests/test_page_safety.py``."""
from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser

from zero2viz.core import transform
from zero2viz.engines import base
from zero2viz.engines.base import THEMES, webkit_fallback_page
from zero2viz.engines.dashboard import build_dashboard
from zero2viz.engines.echarts import EChartsEngine
from zero2viz.engines.guide import build_guide_html
from zero2viz.engines.mpl import MatplotlibEngine
from zero2viz.engines.plotly import PlotlyEngine
from zero2viz.engines.vegalite import VegaLiteEngine

THEME = THEMES["Studio Light"]
EVIL_TITLE = 'x</title><script>window.__pwned=1</script><b x="'
EVIL_VALUE = '</script><img src=x onerror="window.__pwned=1"><!--'


class _Page(HTMLParser):
    """Records what a browser's tokenizer would see: start tags, the title
    text, and the raw content of every script element."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.title = ""
        self.scripts: list[str] = []
        self._in = None

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag in ("title", "script"):
            self._in = tag
            if tag == "script":
                self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "script":
            self.scripts[-1] += data


def _parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    return page


def _spec(kind="bar", title=EVIL_TITLE, **extra):
    spec = {"type": kind, "title": title, "x_label": EVIL_VALUE, "y_label": "y",
            "stacked": False, "theme": THEME,
            "data": {"categories": ["ok", EVIL_VALUE, "Şişli"],
                     "series": [{"name": EVIL_VALUE, "values": [1, 2, 3],
                                 "ids": [[1], [2], [3]]}]}}
    spec.update(extra)
    return spec


def _engines():
    out = [EChartsEngine(), PlotlyEngine(), VegaLiteEngine()]
    if MatplotlibEngine.available():
        out.append(MatplotlibEngine())
    return out


class TestNoBreakOut(unittest.TestCase):

    def assertContained(self, html: str, n_scripts: int, extra_tags=()):
        page = _parse(html)
        allowed = {"html", "head", "meta", "title", "style", "script", "body", "div",
                   *extra_tags}
        self.assertEqual(set(page.tags) - allowed, set(), "injected element")
        self.assertEqual(page.tags.count("script"), n_scripts, "script element split")
        self.assertNotIn("img", [t for t in page.tags if t not in extra_tags])
        return page

    def test_title_and_values_stay_inside_every_engine_page(self):
        for eng in _engines():
            html = eng.build_html(_spec())
            mpl = eng.id == "matplotlib"
            page = self.assertContained(html, 1 if mpl else 2, ("img",) if mpl else ())
            self.assertEqual(page.title, EVIL_TITLE, eng.id)  # shown as text, verbatim
            self.assertNotIn("<title>x</title>", html, eng.id)
            if mpl:
                self.assertEqual(page.tags.count("img"), 1)

    def test_animated_and_faceted_pages_are_contained(self):
        cols = {"c": ["ok", EVIL_VALUE] * 2, "v": [1, 2, 3, 4], "f": [EVIL_VALUE, EVIL_VALUE, "b", "b"]}
        labels, datas, union, bounds = transform.build_frames(
            "bar", cols, [1, 2, 3, 4], cols["f"], x="c", y="v", group="", value="",
            how="sum", single_name=EVIL_VALUE)
        frames = {"field": EVIL_VALUE, "labels": labels, "datas": datas,
                  "categories": union, "bounds": bounds, "interval": 500}
        facets = dict(frames, columns=2, dropped=[EVIL_VALUE])
        for eng in (EChartsEngine(), PlotlyEngine()):
            spec = _spec(data=datas[0], frames=frames)
            self.assertContained(eng.build_html(spec), 2)
        for eng in _engines():
            spec = _spec(data=datas[0], facets=facets)
            mpl = eng.id == "matplotlib"
            self.assertContained(eng.build_html(spec), 1 if mpl else 2,
                                 ("img",) if mpl else ())

    def test_custom_vega_spec_dashboard_guide_and_fallback_are_contained(self):
        custom = {"mark": "bar", "title": EVIL_VALUE,
                  "encoding": {"x": {"field": "c", "type": "nominal"}}}
        self.assertContained(VegaLiteEngine().build_custom_html(_spec(), custom), 2)

        profile = {"title": EVIL_TITLE, "meta": EVIL_VALUE, "kpis": [(EVIL_VALUE, "2")],
                   "insights": [EVIL_VALUE], "fields": [], "frames": None,
                   "tiles": [{"span": 1, "spec": _spec(title=EVIL_VALUE)}]}
        page = _parse(build_dashboard(profile, THEME))
        self.assertNotIn("img", page.tags)
        self.assertEqual(page.tags.count("script"), 2)
        self.assertEqual(page.title, EVIL_TITLE)

        guide = build_guide_html([{"surface": "chart", "title": EVIL_VALUE, "why": EVIL_VALUE,
                                   "how": EVIL_VALUE}], EVIL_TITLE)
        page = _parse(guide)
        self.assertNotIn("img", page.tags)
        self.assertEqual(page.tags.count("script"), 0)

        page = _parse(webkit_fallback_page(EVIL_VALUE, EVIL_VALUE))
        self.assertNotIn("img", page.tags)
        self.assertEqual(page.tags.count("script"), 0)

    def test_embedded_json_reads_back_unchanged(self):
        value = {"a": EVIL_VALUE, "b": "line sep & <!-- ok -->", "c": [1.5, None]}
        text = base.script_json(value)
        for bad in ("<", ">", "&", " "):
            self.assertNotIn(bad, text)
        self.assertEqual(json.loads(text), value)


class TestTitleBridge(unittest.TestCase):

    def test_only_the_plugin_message_shape_selects(self):
        parse_select_title = base.parse_select_title
        self.assertEqual(parse_select_title("o2viz-select:1,2,-3:7"), [1, 2, -3])
        for title in ("o2viz-select:1,2", "o2viz-select:1,x:2", "o2viz-select::2",
                      "o2viz-select:1;2:3", "Parcels o2viz-select:1:1", "o2viz-select:1:2:3",
                      "o2viz-select:1.5:2", "02viz chart", "", None,
                      "o2viz-select:1,2:3\n", "o2viz-select:٣٤:1"):
            self.assertIsNone(parse_select_title(title), title)

    def test_a_title_shaped_like_a_selection_selects_nothing(self):
        # A chart titled "o2viz-select:5:1" would select feature 5 on load.
        page = base.wrap_html("o2viz-select:5:1", "", "", THEMES[base.DEFAULT_THEME])
        title = re.search(r"<title>(.*?)</title>", page).group(1)
        self.assertIsNone(base.parse_select_title(title), title)
        self.assertEqual(base.page_title("Parcels"), "Parcels")

    def test_page_bridge_only_sends_integer_ids(self):
        self.assertIn("Math.floor(v) === v", base.BRIDGE_JS)


class TestExportContract(unittest.TestCase):

    def test_every_engine_page_defines_o2viz_export(self):
        for eng in _engines():
            html = eng.build_html(_spec(title="ok"))
            self.assertIn("window.o2vizExport = function (format, width, height, scale)",
                          html, eng.id)
        cols = {"c": ["a", "b"] * 2, "v": [1, 2, 3, 4], "f": [1, 1, 2, 2]}
        labels, datas, union, bounds = transform.build_frames(
            "bar", cols, [1, 2, 3, 4], cols["f"], x="c", y="v", group="", value="",
            how="sum", single_name="v")
        frames = {"field": "f", "labels": labels, "datas": datas, "categories": union,
                  "bounds": bounds, "interval": 500}
        for eng in (EChartsEngine(), PlotlyEngine()):
            html = eng.build_html(_spec(title="ok", data=datas[0], frames=frames))
            self.assertIn("window.o2vizExport = function", html, eng.id)

    def test_export_uses_each_engines_own_vector_path(self):
        self.assertIn('Plotly.toImage(gd, {format: "svg"',
                      PlotlyEngine().build_html(_spec(title="ok")))
        ec = EChartsEngine().build_html(_spec(title="ok"))
        self.assertIn('renderer: format === "svg" ? "svg" : "canvas"', ec)
        self.assertIn("renderToSVGString()", ec)
        vl = VegaLiteEngine().build_html(_spec(title="ok"))
        self.assertIn("exp.toSVG()", vl)
        self.assertIn('exp.toImageURL("png"', vl)


if __name__ == "__main__":
    unittest.main()
