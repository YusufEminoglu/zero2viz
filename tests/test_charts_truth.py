# -*- coding: utf-8 -*-
"""Pure tests: every chart tells the truth about the data (v0.20 set, items
B, E, F and G — engine and core halves). Run with pytest from the plugin
folder: ``py -3 -m pytest -o pythonpath=.. tests/test_charts_truth.py``."""
from __future__ import annotations

import datetime
import os
import re
import statistics
import sys
import tempfile
import time
import unittest
from unittest import mock

from zero2viz.core import requirements, stats, transform
from zero2viz.engines.base import THEMES
from zero2viz.engines.echarts import EChartsEngine
from zero2viz.engines.mpl import MatplotlibEngine
from zero2viz.engines.plotly import PlotlyEngine
from zero2viz.engines.vegalite import VegaLiteEngine

THEME = THEMES["Studio Light"]
CODES = ["30", "4", "100", "(null)", "Other", "2024-03"]


def _bar(cats, vals, kind="bar", **extra):
    spec = {"type": kind, "title": "t", "x_label": "x", "y_label": "y", "stacked": False,
            "theme": THEME,
            "data": {"categories": list(cats),
                     "series": [{"name": "y", "values": list(vals),
                                 "ids": [[i] for i in range(len(cats))]}]}}
    spec.update(extra)
    return spec


class FakeQDate:
    """Duck-typed stand-in for QDate / QDateTime (no Qt in pure tests)."""

    def __init__(self, value):
        self.value = value

    def isValid(self):
        return self.value is not None

    def toPyDate(self):
        if self.value is None:
            raise ValueError("null date")
        return self.value

    def __str__(self):  # what str(QDate) prints
        return f"PyQt5.QtCore.QDate({self.value})"


class TestPlotlyCategoryAxes(unittest.TestCase):

    def test_category_charts_type_x_as_category(self):
        eng = PlotlyEngine()
        for kind in ("bar", "line", "area", "lollipop"):
            _, layout = eng._figure(_bar(CODES, [9, 7, 5, 3, 1, 2], kind))
            self.assertEqual(layout["xaxis"].get("type"), "category", kind)
        specs = {
            "histogram": {"categories": ["1–2", "2–3"], "values": [3, 4]},
            "box": {"groups": ["30", "4"], "stats": [[1, 2, 3, 4, 5], [2, 3, 4, 5, 6]]},
            "errorband": {"categories": ["30", "4"], "series": [
                {"name": "a", "mean": [1, 2], "lo": [0, 1], "hi": [2, 3], "ids": [[1], [2]]}]},
            "errorbar": {"categories": ["30", "4"], "series": [
                {"name": "a", "mean": [1, 2], "lo": [0, 1], "hi": [2, 3], "ids": [[1], [2]]}]},
            "pareto": {"categories": ["30", "4"], "values": [5, 3], "cum": [62.5, 100.0],
                       "ids": [[1], [2]]},
        }
        for kind, data in specs.items():
            _, layout = eng._figure({"type": kind, "title": "t", "x_label": "x",
                                     "y_label": "y", "theme": THEME, "data": data})
            self.assertEqual(layout["xaxis"].get("type"), "category", kind)
        # numeric axes stay numeric
        _, layout = eng._figure({"type": "scatter", "title": "t", "x_label": "x",
                                 "y_label": "y", "theme": THEME,
                                "data": {"series": [{"name": "p", "points": [[1, 2, None, 1]]}],
                                         "trend": None}})
        self.assertNotEqual(layout["xaxis"].get("type"), "category")

    def test_heatmap_types_both_axes_as_category(self):
        _, layout = PlotlyEngine()._figure({
            "type": "heatmap", "title": "h", "x_label": "x", "y_label": "y", "theme": THEME,
            "data": {"x_cats": ["10", "2", "1"], "y_cats": ["2024-01", "2024-02"],
                     "cells": [[0, 0, 1], [1, 1, 2]], "vmin": 1, "vmax": 2}})
        self.assertEqual(layout["xaxis"].get("type"), "category")
        self.assertEqual(layout["yaxis"].get("type"), "category")

    def test_frames_and_facets_keep_category_axes(self):
        cols = {"c": ["30", "4", "30", "100"], "v": [1, 2, 3, 4], "f": [1, 1, 2, 2]}
        labels, datas, union, bounds = transform.build_frames(
            "bar", cols, [1, 2, 3, 4], cols["f"], x="c", y="v", group="", value="",
            how="sum", single_name="v")
        spec = _bar(union, datas[0]["series"][0]["values"])
        spec["frames"] = {"field": "f", "labels": labels, "datas": datas,
                          "categories": union, "bounds": bounds, "interval": 500}
        _, layout, _ = PlotlyEngine()._animated_figure(spec)
        self.assertEqual(layout["xaxis"].get("type"), "category")


class TestTopNOther(unittest.TestCase):

    def setUp(self):
        # 20 districts, each with mean 10 (rows 5 and 15)
        self.xs = [f"d{i:02d}" for i in range(20) for _ in range(2)]
        self.ys = [5 if j % 2 == 0 else 15 for j in range(40)]

    def _true(self, how, rows):
        return {"mean": statistics.mean(rows), "median": statistics.median(rows),
                "max": max(rows), "min": min(rows), "std": statistics.stdev(rows),
                "count": len(rows), "sum": sum(rows)}[how]

    def test_other_uses_the_chosen_aggregate_on_the_merged_rows(self):
        for how in ("mean", "median", "max", "min", "std", "count", "sum"):
            c, v, i = transform.group_rows(self.xs, self.ys, list(range(40)), how)
            c, v, i = transform.sort_cats(c, v, i, "value_desc")   # the dock's order
            c2, v2, i2 = transform.topn_collapse(c, v, i, 5)
            self.assertEqual(c2[-1], "Other")
            other_rows = [self.ys[j] for j in i2[-1]]
            self.assertEqual(len(other_rows), 30)
            self.assertAlmostEqual(v2[-1], self._true(how, other_rows), msg=how)

    def test_mean_other_is_the_true_mean_not_a_sum_of_means(self):
        c, v, i = transform.group_rows(self.xs, self.ys, list(range(40)), "mean")
        _, v2, _ = transform.topn_collapse(c, v, i, 5)
        self.assertAlmostEqual(v2[-1], 10.0)  # was 150.0 (15 means of 10 summed)

    def test_pareto_pipeline_and_explicit_arguments(self):
        c, v, i = transform.group_rows(self.xs, self.ys, list(range(40)), "max")
        c, v, i = transform.topn_collapse(c, v, i, 3)
        _, vals, cum, _ = transform.pareto_rows(c, v, i)
        self.assertEqual(vals[0], 15.0)
        self.assertLessEqual(max(cum), 100.0)
        # raw (unaggregated) values keep the documented sum
        _, v3, _ = transform.topn_collapse(["a", "b", "c"], [3.0, 2.0, 1.0], None, 1)
        self.assertEqual(v3, [3.0, 3.0])
        _, v4, _ = transform.topn_collapse(["a", "b", "c"], [3.0, 2.0, 1.0], None, 1,
                                           how="mean", samples=[[3.0], [2.0], [1.0]],
                                           counts=[1, 1, 1])
        self.assertEqual(v4, [3.0, 1.5])


class TestDates(unittest.TestCase):

    def test_temporal_values_become_iso_text(self):
        self.assertEqual(transform._key(datetime.date(2024, 2, 1)), "2024-02-01")
        self.assertEqual(transform._key(datetime.datetime(2024, 2, 1, 8, 0)),
                         "2024-02-01T08:00:00")
        self.assertEqual(transform._key(FakeQDate(datetime.date(2024, 10, 1))), "2024-10-01")
        self.assertEqual(transform._key(FakeQDate(None)), "(null)")
        self.assertEqual(stats.temporal_iso("2024-01-01"), None)

    def test_dates_sort_as_dates(self):
        raw = [FakeQDate(datetime.date(2024, 2, 1)), FakeQDate(datetime.date(2024, 10, 1)),
               None, FakeQDate(datetime.date(2024, 1, 1)), FakeQDate(datetime.date(2024, 2, 1))]
        cats, vals, _ = transform.group_rows(raw, [], list(range(5)), "count")
        self.assertEqual(cats, ["2024-01-01", "2024-02-01", "2024-10-01", "(null)"])
        self.assertEqual(list(vals), [1.0, 2.0, 1.0, 1.0])
        self.assertFalse(any("QDate" in c for c in cats))
        labels, _ = transform.frame_groups(raw)
        self.assertEqual(labels, ["2024-01-01", "2024-02-01", "2024-10-01", "(null)"])
        cats2, series = transform.pivot_rows(["2024-10-01", "2024-02-01"], ["a", "b"], [1, 2],
                                             [1, 2], "sum")
        self.assertEqual(cats2, ["2024-02-01", "2024-10-01"])
        # other text keeps its first-appearance order
        self.assertEqual(transform.group_rows(["b", "a"], [], [1, 2], "count")[0], ["b", "a"])


class TestHistogramLabels(unittest.TestCase):

    def _check(self, values, bins=20):
        labels, counts = stats.histogram(values, bins)
        self.assertEqual(len(labels), bins)
        self.assertEqual(len(set(labels)), len(labels), labels)
        self.assertEqual(sum(counts), len(values))
        return labels

    def test_years_get_distinct_bin_labels(self):
        labels = self._check([2000 + (i % 11) for i in range(1100)])
        self.assertEqual(labels[0], "2,000–2,000.5")

    def test_tiny_steps_get_distinct_bin_labels(self):
        labels = self._check([0.0001 + i * 0.0000008 for i in range(1000)])
        self.assertTrue(labels[0].startswith("0.0001–"), labels[0])

    def test_other_ranges_stay_distinct_and_readable(self):
        self._check([1000 + (i % 10) for i in range(500)])
        labels = self._check([i / 999 for i in range(1000)])
        self.assertEqual(labels[:2], ["0–0.05", "0.05–0.1"])  # unchanged style


class TestAggregateNone(unittest.TestCase):

    def test_null_y_is_skipped_not_drawn_as_zero(self):
        cats, vals, ids = transform.raw_rows(["A", "B", "C", "D", "E"],
                                             [3.0, None, "", "x", 7], [10, 11, 12, 13, 14])
        self.assertEqual(cats, ["A", "E"])
        self.assertEqual(vals, [3.0, 7.0])
        self.assertEqual(ids, [[10], [14]])
        self.assertNotIn(0.0, vals)

    def test_repeated_x_gets_one_slot_per_feature_in_every_engine(self):
        cats, vals, ids = transform.raw_rows(["A", "A", "B", "A (2)"], [1.0, 2.0, 3.0, True],
                                             [1, 2, 3, 4])
        self.assertEqual(cats, ["A", "A (2)", "B", "A (2) (2)"])
        self.assertEqual(vals, [1.0, 2.0, 3.0, 1.0])
        spec = {"type": "bar", "title": "t", "x_label": "x", "y_label": "y", "theme": THEME,
                "data": {"categories": cats, "series": [{"name": "y", "values": vals,
                                                         "ids": ids}]}}
        traces, _ = PlotlyEngine().figure(spec)
        self.assertEqual(len(set(traces[0]["x"])), 4)
        rows = VegaLiteEngine().vl_spec(spec)["data"]["values"]
        self.assertEqual(len({r["c"] for r in rows}), 4)
        self.assertEqual(len(EChartsEngine().page_option(spec)["xAxis"]["data"]), 4)


class TestBarRace(unittest.TestCase):

    def _race_spec(self, **options):
        cols = {"c": ["a", "b", "c"] * 3, "v": [1, 2, 3, 6, 5, 1, 2, 9, 4],
                "year": [2000] * 3 + [2001] * 3 + [2002] * 3}
        labels, datas, union, bounds = transform.build_frames(
            "bar", cols, list(range(9)), cols["year"], x="c", y="v", group="", value="",
            how="sum", single_name="sum(v)")
        spec = _bar(union, datas[0]["series"][0]["values"])
        spec["frames"] = {"field": "year", "labels": labels, "datas": datas,
                          "categories": union, "bounds": bounds, "interval": 600}
        if options:
            spec["options"] = options
        return spec

    def test_plotly_race_re_sorts_every_frame(self):
        _, layout, frames = PlotlyEngine()._animated_figure(self._race_spec())
        orders = [f.get("layout", {}).get("xaxis", {}).get("categoryarray") for f in frames]
        self.assertEqual(orders, [["c", "b", "a"], ["a", "b", "c"], ["b", "c", "a"]])
        self.assertEqual(layout["xaxis"].get("categoryarray"), ["c", "b", "a"])
        self.assertEqual(layout["xaxis"].get("categoryorder"), "array")

    def test_echarts_race_re_sorts_every_frame(self):
        opt = EChartsEngine()._timeline_option(self._race_spec())
        orders = [o.get("xAxis", {}).get("data") for o in opt["options"]]
        self.assertEqual(orders, [["c", "b", "a"], ["a", "b", "c"], ["b", "c", "a"]])
        self.assertEqual(opt["baseOption"]["xAxis"]["data"], ["c", "b", "a"])
        # each frame's bars follow its axis order, and a category keeps its colour
        colours = {}
        for o in opt["options"]:
            values = [it["value"] for it in o["series"][0]["data"]]
            self.assertEqual(values, sorted(values, reverse=True))
            for cat, it in zip(o["xAxis"]["data"], o["series"][0]["data"]):
                colours.setdefault(cat, set()).add(it["itemStyle"]["color"])
        self.assertTrue(all(len(c) == 1 for c in colours.values()))
        self.assertEqual(len({next(iter(c)) for c in colours.values()}), 3)

    def test_race_can_be_switched_off(self):
        _, _, frames = PlotlyEngine()._animated_figure(self._race_spec(race=False))
        self.assertTrue(all("layout" not in f for f in frames))
        opt = EChartsEngine()._timeline_option(self._race_spec(race=False))
        self.assertTrue(all("xAxis" not in o for o in opt["options"]))
        # and a race is on by default (fails where the race never re-sorts)
        opt = EChartsEngine()._timeline_option(self._race_spec())
        self.assertTrue(all("xAxis" in o for o in opt["options"]))


class TestParetoAndBooleans(unittest.TestCase):

    def test_pareto_refuses_negative_values_with_a_message(self):
        with self.assertRaisesRegex(ValueError, "zero or more"):
            transform.pareto_rows(["a", "b", "c"], [-5.0, 10.0, 5.0], None)
        cats, vals, cum, _ = transform.pareto_rows(["a", "b"], [0.0, 4.0], None)
        self.assertEqual(cum, [100.0, 100.0])

    def test_booleans_are_counted(self):
        xs, ys = ["a", "a", "a", "b"], [True, False, True, False]
        cats, sums, _ = transform.group_rows(xs, ys, [1, 2, 3, 4], "sum")
        self.assertEqual((cats, list(sums)), (["a", "b"], [2.0, 0.0]))
        _, means, _ = transform.group_rows(xs, ys, [1, 2, 3, 4], "mean")
        self.assertAlmostEqual(means[0], 2 / 3)
        self.assertEqual(stats.aggregate(xs, ys, "sum"), (["a", "b"], [2.0, 0.0]))
        _, series = transform.pivot_rows(xs, ["g"] * 4, ys, [1, 2, 3, 4], "sum")
        self.assertEqual(series[0]["values"], [2.0, 0.0])
        self.assertIsNone(stats.to_float(True))  # still not a histogram value


class TestFrameOrder(unittest.TestCase):

    def test_numeric_frames_sort_numerically_with_null_last(self):
        self.assertEqual(transform.frame_groups(["10", "2", "1", None])[0],
                         ["1", "2", "10", "(null)"])
        self.assertEqual(transform.union_categories([["10", "2"], ["1", "(null)"]]),
                         ["1", "2", "10", "(null)"])
        self.assertEqual(transform.frame_groups(["b", None, "a"])[0], ["a", "b", "(null)"])

    def test_count_chart_without_y_animates_and_facets(self):
        # A count chart has no Y field; animating or faceting it used to fail
        # with "list index out of range".
        cols = {"kind": ["a", "b", "a", "a"], "year": ["2020", "2020", "2021", "2021"]}
        fids = [1, 2, 3, 4]
        frames = transform.build_frames(
            "bar", cols, fids, cols["year"], x="kind", y="", group="", value="",
            how="count")
        self.assertIsNotNone(frames)
        labels, datas, union, _bounds = frames
        self.assertEqual(labels, ["2020", "2021"])
        self.assertEqual(union, ["a", "b"])
        self.assertEqual([list(d["series"][0]["values"]) for d in datas],
                         [[1.0, 1.0], [2.0, 0.0]])
        facets = transform.build_facets(
            "bar", cols, fids, cols["year"], x="kind", y="", group="", value="",
            how="count")
        self.assertIsNotNone(facets)
        self.assertEqual([list(d["series"][0]["values"]) for d in facets[1]],
                         [[1.0, 1.0], [2.0, 0.0]])


class TestOrientationAndReversedAxes(unittest.TestCase):
    """GitHub #1: horizontal bars and reversed axes, as engine options."""

    def test_plotly(self):
        traces, layout = PlotlyEngine().figure(_bar(["a", "b"], [1, 2],
                                                    options={"horizontal": True}))
        self.assertEqual(traces[0]["orientation"], "h")
        self.assertEqual(traces[0]["y"], ["a", "b"])
        self.assertEqual(layout["yaxis"]["type"], "category")
        self.assertEqual(layout["yaxis"]["autorange"], "reversed")  # first on top
        _, layout = PlotlyEngine().figure(_bar(["a", "b"], [1, 2], options={
            "horizontal": True, "reverse_x": True, "reverse_y": True}))
        self.assertEqual(layout["xaxis"]["autorange"], "reversed")
        self.assertIs(layout["yaxis"]["autorange"], True)
        _, layout = PlotlyEngine().figure(_bar(["a", "b"], [1, 2], kind="line",
                                               options={"reverse_y": True}))
        self.assertEqual(layout["yaxis"]["autorange"], "reversed")

    def test_echarts(self):
        opt = EChartsEngine().page_option(_bar(["a", "b"], [1, 2], options={
            "horizontal": True}))
        self.assertEqual(opt["yAxis"]["type"], "category")
        self.assertTrue(opt["yAxis"]["inverse"])
        self.assertEqual(opt["xAxis"]["type"], "value")
        opt = EChartsEngine().page_option(_bar(["a", "b"], [1, 2], options={
            "reverse_x": True, "reverse_y": True}))
        self.assertTrue(opt["xAxis"]["inverse"])
        self.assertTrue(opt["yAxis"]["inverse"])

    def test_vegalite(self):
        vl = VegaLiteEngine().page_spec(_bar(["a", "b"], [1, 2], options={
            "horizontal": True, "reverse_x": True}))
        self.assertEqual(vl["encoding"]["y"]["field"], "c")
        self.assertEqual(vl["encoding"]["x"]["field"], "v")
        self.assertTrue(vl["encoding"]["x"]["scale"]["reverse"])

    def test_matplotlib_draws_them(self):
        if not MatplotlibEngine.available():
            self.skipTest("matplotlib not installed")
        svg = MatplotlibEngine().render(_bar(["a", "b"], [1, 2], options={
            "horizontal": True, "reverse_x": True}), "svg").decode("utf-8")
        self.assertIn("<svg", svg)


class TestLayerColours(unittest.TestCase):
    """options["category_colors"]: mapped categories use the symbol colour."""

    CMAP = {"b": "#ff0000", "bad": "red"}

    def test_single_series_bars_and_pies(self):
        spec = _bar(["a", "b", "c"], [1, 2, 3], options={"category_colors": self.CMAP})
        p0 = THEME["palette"][0]
        traces, _ = PlotlyEngine().figure(spec)
        self.assertEqual(traces[0]["marker"]["color"], [p0, "#ff0000", p0])
        items = EChartsEngine().page_option(spec)["series"][0]["data"]
        self.assertEqual([it["itemStyle"]["color"] for it in items], [p0, "#ff0000", p0])
        enc = VegaLiteEngine().vl_spec(spec)["encoding"]["color"]
        self.assertEqual(enc["scale"], {"domain": ["a", "b", "c"],
                                        "range": [p0, "#ff0000", p0]})
        pie = {"type": "pie", "title": "p", "x_label": "x", "y_label": "y", "theme": THEME,
               "options": {"category_colors": self.CMAP},
               "data": {"categories": ["a", "b"], "values": [1, 2], "ids": [[1], [2]]}}
        traces, _ = PlotlyEngine().figure(pie)
        self.assertEqual(traces[0]["marker"]["colors"], [p0, "#ff0000"])
        items = EChartsEngine().page_option(pie)["series"][0]["data"]
        self.assertEqual(items[1]["itemStyle"]["color"], "#ff0000")

    def test_series_named_after_a_category_use_its_colour(self):
        spec = {"type": "line", "title": "t", "x_label": "x", "y_label": "y", "theme": THEME,
                "options": {"category_colors": self.CMAP},
                "data": {"categories": ["2020", "2021"],
                         "series": [{"name": "a", "values": [1, 2], "ids": [[1], [2]]},
                                    {"name": "b", "values": [2, 3], "ids": [[3], [4]]}]}}
        traces, _ = PlotlyEngine().figure(spec)
        self.assertEqual(traces[1]["line"]["color"], "#ff0000")
        self.assertNotIn("color", traces[0].get("line", {}))
        series = EChartsEngine().page_option(spec)["series"]
        self.assertEqual(series[1]["lineStyle"]["color"], "#ff0000")
        enc = VegaLiteEngine().vl_spec(spec)["encoding"]["color"]
        self.assertEqual(enc["scale"]["range"][1], "#ff0000")
        if MatplotlibEngine.available():
            self.assertIn("<svg", MatplotlibEngine().render(spec, "svg").decode("utf-8"))


class TestMatplotlibHygiene(unittest.TestCase):

    def setUp(self):
        if not MatplotlibEngine.available():
            self.skipTest("matplotlib not installed")

    def test_backend_and_rcparams_are_left_unchanged(self):
        import matplotlib
        previous = matplotlib.get_backend()
        matplotlib.use("svg", force=True)
        try:
            with matplotlib.rc_context({"axes.grid": False, "font.family": ["serif"]}):
                backend = matplotlib.get_backend()
                before = matplotlib.rcParams.copy()
                html = MatplotlibEngine().build_html(_bar(["İzmir", "Şişli"], [1, 2]))
                self.assertIn("data:image/png;base64,", html)
                self.assertEqual(matplotlib.get_backend(), backend)
                self.assertEqual(matplotlib.rcParams, before)
        finally:
            matplotlib.use(previous, force=True)

    def test_large_bar_counts_are_capped_with_a_message(self):
        n = 5000
        eng = MatplotlibEngine()
        t0 = time.perf_counter()
        html = eng.build_html(_bar([f"c{i}" for i in range(n)], [float(i % 7) for i in range(n)]))
        self.assertLess(time.perf_counter() - t0, 30.0)
        self.assertIn("first 300 of 5,000 categories", eng.last_note)
        self.assertIn("first 300 of 5,000 categories", html)

    def test_page_carries_the_savefig_svg(self):
        html = MatplotlibEngine().build_html(_bar(["a"], [1]))
        self.assertIn("var O2VIZ_SVG = \"\\u003c?xml", html)


class TestInstallHint(unittest.TestCase):

    def test_hint_uses_the_qgis_python_not_the_qgis_program(self):
        with tempfile.TemporaryDirectory(prefix="o2viz py ") as prefix:
            if os.name == "nt":
                exe, program = os.path.join(prefix, "python.exe"), r"C:\QGIS\bin\qgis-bin.exe"
            else:
                ver = f"{sys.version_info.major}.{sys.version_info.minor}"
                os.makedirs(os.path.join(prefix, "bin"))
                exe, program = os.path.join(prefix, "bin", f"python{ver}"), "/usr/bin/qgis"
            open(exe, "w").close()
            with mock.patch.object(sys, "executable", program), \
                    mock.patch.object(sys, "exec_prefix", prefix):
                cmd = requirements.install_command(["matplotlib"])
                line = requirements.install_command_str(["matplotlib"])
            self.assertEqual(cmd[0], exe)
            self.assertEqual(cmd[1:], ["-m", "pip", "install", "--user", "matplotlib"])
            self.assertNotIn("qgis-bin", line)
            self.assertTrue(line.startswith(('"', "'")), line)  # path with a space is quoted
        with mock.patch.object(sys, "executable", os.path.join("x", "python3.12")):
            self.assertEqual(requirements.python_executable(), os.path.join("x", "python3.12"))


class TestGuideIsTrue(unittest.TestCase):

    def test_sections_are_numbered_in_order_and_listed(self):
        from zero2viz.engines.guide import build_guide_html
        html = build_guide_html()
        found = re.findall(r'<section id="(\w+)"><h2><span class="n">(\d+)</span>', html)
        self.assertEqual([int(n) for _, n in found], list(range(1, len(found) + 1)))
        nav = html.split("<nav>")[1].split("</nav>")[0]
        self.assertEqual(re.findall(r'href="#(\w+)"', nav), [i for i, _ in found])

    def test_false_sentences_are_gone(self):
        from zero2viz.engines.guide import build_guide_html
        html = build_guide_html()
        for claim in ("capture the active embedded view", "uses QGIS print output",
                      "click to install", "Fixed in 0.9.1", "quartiles and outliers",
                      "use the active rendered view"):
            self.assertNotIn(claim, html)


if __name__ == "__main__":
    unittest.main()
