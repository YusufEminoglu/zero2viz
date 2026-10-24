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


class TestThemeProvider(unittest.TestCase):

    def test_catalog_is_versioned_complete_and_isolated(self):
        from zero2viz.core.theme_provider import API_ID, theme_catalog
        first = theme_catalog()
        self.assertEqual(first["api"], API_ID)
        self.assertEqual(first["api_version"], 1)
        self.assertGreaterEqual(len(first["themes"]), 4)
        required = {
            "id", "label", "palette", "background", "text", "grid",
            "font_family", "title_size_pt", "label_size_pt", "line_width_mm",
        }
        self.assertTrue(all(required <= set(theme) for theme in first["themes"]))
        first["themes"][0]["palette"][0] = "#000000"
        self.assertNotEqual(theme_catalog()["themes"][0]["palette"][0], "#000000")


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


def _facet_fixture():
    """Deterministic rows: 5 regions of different sizes, 3 uses, 2 tenures."""
    regions, uses, tenure, area, price, pop = [], [], [], [], [], []
    sizes = {"North": 30, "South": 24, "East": 18, "West": 12, "Isle": 3}
    k = 0
    for region, n in sizes.items():
        for i in range(n):
            regions.append(region)
            uses.append(("housing", "retail", "park")[i % 3])
            tenure.append(("owner", "renter")[i % 2])
            area.append(10.0 + (k % 17) * 3.0)
            price.append(100.0 + (k % 11) * 20.0)
            pop.append(1 + k % 9)
            k += 1
    cols = {"region": regions, "use": uses, "tenure": tenure,
            "area": area, "price": price, "pop": pop}
    return cols, list(range(1, k + 1))


class TestSmallMultiples(unittest.TestCase):

    def test_facet_groups_keeps_largest_in_natural_order(self):
        from zero2viz.core.transform import facet_groups
        labels, idx, dropped = facet_groups(
            ["b", "a", "a", "c", "c", "c", "d"], cap=2)
        self.assertEqual(labels, ["a", "c"])
        self.assertEqual(idx, [[1, 2], [3, 4, 5]])
        self.assertEqual(dropped, ["b", "d"])
        years, _, none = facet_groups([2010, 2002, 2002, 2001], cap=12)
        self.assertEqual(years, ["2001", "2002", "2010"])
        self.assertEqual(none, [])

    def test_facet_columns_are_near_square_and_capped(self):
        from zero2viz.core.transform import facet_columns
        self.assertEqual([facet_columns(n) for n in (1, 2, 3, 4, 6, 9, 12, 16)],
                         [1, 2, 3, 2, 3, 3, 4, 4])

    def test_panels_share_categories_series_and_value_range(self):
        from zero2viz.core.transform import build_facets
        cols, fids = _facet_fixture()
        labels, datas, union, bounds, dropped = build_facets(
            "bar", cols, fids, cols["region"], x="use", y="area",
            group="tenure", value="", how="sum", cap=4)
        self.assertEqual(labels, ["East", "North", "South", "West"])
        self.assertEqual(dropped, ["Isle"])
        self.assertEqual(union, ["housing", "park", "retail"])
        for data in datas:
            self.assertEqual(data["categories"], union)
            self.assertEqual([s["name"] for s in data["series"]], ["owner", "renter"])
        # every panel's bars fall inside the shared range, and the range is tight
        values = [v for d in datas for s in d["series"] for v in s["values"]]
        self.assertEqual(bounds["y"][1], max(values))
        # the North panel's total equals the North rows' total
        north = datas[labels.index("North")]
        expected = sum(a for a, r in zip(cols["area"], cols["region"]) if r == "North")
        self.assertAlmostEqual(sum(sum(s["values"]) for s in north["series"]), expected)
        # ids follow their panel: no feature appears in two panels
        seen = set()
        for d in datas:
            for s in d["series"]:
                for ids in s["ids"]:
                    self.assertFalse(seen & set(ids))
                    seen |= set(ids)

    def test_single_group_or_unchartable_input_is_refused(self):
        from zero2viz.core.transform import build_facets
        cols, fids = _facet_fixture()
        self.assertIsNone(build_facets(
            "bar", cols, fids, ["one"] * len(fids), x="use", y="area",
            group="", value="", how="sum"))
        self.assertIsNone(build_facets(
            "box", cols, fids, cols["region"], x="use", y="area",
            group="", value="", how="sum"))

    def _spec(self, kind, cap=12):
        from zero2viz.core.transform import build_facets, facet_columns
        from zero2viz.engines.base import THEMES
        cols, fids = _facet_fixture()
        roles = {"scatter": dict(x="area", y="price", group="tenure", value=""),
                 "pie": dict(x="use", y="area", group="", value="")}
        kw = roles.get(kind, dict(x="use", y="area", group="tenure", value=""))
        labels, datas, union, bounds, dropped = build_facets(
            kind, cols, fids, cols["region"], how="sum", cap=cap,
            single_name="value", **kw)
        return {"type": kind, "title": "Facets", "x_label": kw["x"],
                "y_label": kw["y"], "stacked": False, "theme": THEMES["Studio Light"],
                "data": datas[0],
                "facets": {"field": "region", "labels": labels, "datas": datas,
                           "categories": union, "bounds": bounds,
                           "columns": facet_columns(len(labels)),
                           "dropped": dropped}}

    def test_echarts_builds_one_grid_per_panel_with_pinned_colours(self):
        from zero2viz.engines.echarts import EChartsEngine
        spec = self._spec("bar", cap=4)
        opt = EChartsEngine()._facet_option(spec)
        self.assertEqual(opt["__facets"], 4)
        self.assertEqual(len(opt["grid"]), 4)
        self.assertEqual([a["gridIndex"] for a in opt["xAxis"]], [0, 1, 2, 3])
        self.assertEqual(len(opt["series"]), 8)  # 4 panels x 2 tenures
        colours = {}
        for s in opt["series"]:
            colours.setdefault(s["name"], set()).add(s["itemStyle"]["color"])
        self.assertEqual({k: len(v) for k, v in colours.items()}, {"owner": 1, "renter": 1})
        self.assertNotEqual(colours["owner"], colours["renter"])
        # one shared value axis maximum across panels
        self.assertEqual(len({a["max"] for a in opt["yAxis"]}), 1)
        self.assertIn("1 more region value not shown", opt["title"][0]["subtext"])
        self.assertIn('"__facets": 4', EChartsEngine().build_html(spec))

    def test_echarts_pie_panels_colour_slices_by_category(self):
        from zero2viz.engines.echarts import EChartsEngine
        opt = EChartsEngine()._facet_option(self._spec("pie"))
        self.assertNotIn("grid", opt)
        slice_colours = {}
        for s in opt["series"]:
            for item in s["data"]:
                slice_colours.setdefault(item["name"], set()).add(item["itemStyle"]["color"])
        self.assertTrue(all(len(v) == 1 for v in slice_colours.values()))

    def test_plotly_builds_subplots_with_one_legend_entry_per_series(self):
        from zero2viz.engines.plotly import PlotlyEngine
        traces, layout = PlotlyEngine()._facet_figure(self._spec("scatter"))
        self.assertEqual(layout["meta"]["o2viz_facets"], 5)
        self.assertIn("xaxis5", layout)
        self.assertNotIn("xaxis6", layout)
        shown = [t["name"] for t in traces if t.get("showlegend")]
        self.assertEqual(sorted(shown), ["owner", "renter"])
        per_name = {}
        for t in traces:
            per_name.setdefault(t["name"], set()).add(t["marker"]["color"])
        self.assertTrue(all(len(v) == 1 for v in per_name.values()))
        ranges = {tuple(layout[k]["range"]) for k in layout if k.startswith("yaxis")}
        self.assertEqual(len(ranges), 1)

    def test_stacked_panels_bound_the_stack_and_stack_per_panel(self):
        from zero2viz.core.transform import build_facets
        from zero2viz.engines.echarts import EChartsEngine
        cols, fids = _facet_fixture()
        kw = dict(x="use", y="area", group="tenure", value="", how="sum", cap=4)
        flat = build_facets("area", cols, fids, cols["region"], **kw)
        stack = build_facets("area", cols, fids, cols["region"], stacked=True, **kw)
        tallest = max(sum(s["values"][j] for s in d["series"])
                      for d in stack[1] for j in range(len(stack[2])))
        self.assertEqual(stack[3]["y"][1], tallest)
        self.assertLess(flat[3]["y"][1], tallest)  # unstacked range would clip
        spec = self._spec("bar", cap=4)
        spec["stacked"] = True
        opt = EChartsEngine()._facet_option(spec)
        stacks = {s["stack"] for s in opt["series"]}
        self.assertEqual(len(stacks), 4)  # one stack per panel, never shared

    def test_fixed_axis_ends_on_a_tick(self):
        from zero2viz.engines.echarts import _axis_fit
        for lo, hi in ((0, 13), (0, 5855), (12.3, 97.1), (-40, 260), (0.01, 0.93), (0, 1)):
            a, b, step = _axis_fit(lo, hi)
            self.assertLessEqual(a, lo)
            self.assertGreaterEqual(b, hi)
            self.assertAlmostEqual((b - a) / step, round((b - a) / step))
            if float(lo).is_integer() and float(hi).is_integer():
                self.assertTrue(float(step).is_integer(), (lo, hi, step))
        self.assertEqual(_axis_fit(0, 5855)[1], 7000.0)
        self.assertEqual(_axis_fit(0.01, 0.93)[0], 0.0)  # no padding below zero

    def test_vegalite_and_matplotlib_build_facets(self):
        from zero2viz.engines import engines
        spec = self._spec("bar", cap=4)
        vl = [e for e in engines() if e.id == "vegalite"][0]
        self.assertIn("bar", vl.facets)
        vl_dict = vl.vl_spec(spec)
        self.assertEqual(vl_dict["usermeta"]["__facets"], 4)
        self.assertEqual(len(vl_dict["concat"]), 4)
        self.assertEqual(vl_dict["columns"], 2)
        html = vl.build_html(spec)
        self.assertIn("housing", html)
        self.assertIn('"__facets": 4', html)

        mpl = [e for e in engines() if e.id == "matplotlib"][0]
        self.assertIn("bar", mpl.facets)
        if mpl.available():
            mpl_html = mpl.build_html(spec)
            self.assertIn("window.__o2vizFacetCount = 4;", mpl_html)
            self.assertIn("data:image/png;base64,", mpl_html)


class TestStatisticalEnhancements(unittest.TestCase):

    def test_kde_and_violin_clamp_non_negative_data_at_zero(self):
        from zero2viz.core.stats import kde_points
        from zero2viz.core.transform import violin_rows
        vals = [0.0, 2.0, 5.0, 10.0, 50.0, 120.0]
        pts = kde_points(vals)
        self.assertTrue(pts)
        self.assertGreaterEqual(pts[0][0], 0.0)
        groups, polys, meds = violin_rows(["A"], {"A": vals})
        self.assertEqual(groups, ["A"])
        self.assertTrue(all(p[1] >= 0.0 for p in polys[0]))
        self.assertEqual(meds, [7.5])

    def test_std_and_iqr_aggregations(self):
        from zero2viz.core.stats import aggregate
        from zero2viz.core.transform import group_rows
        xs = ["A", "A", "A", "A", "B", "B"]
        ys = [10.0, 20.0, 30.0, 40.0, 5.0, 5.0]
        cats, stds = aggregate(xs, ys, "std")
        self.assertEqual(cats, ["A", "B"])
        self.assertGreater(stds[0], 10.0)
        self.assertEqual(stds[1], 0.0)
        cats_i, iqrs, _ = group_rows(xs, ys, list(range(6)), "iqr")
        self.assertEqual(cats_i, ["A", "B"])
        self.assertAlmostEqual(iqrs[0], 15.0)
        self.assertEqual(iqrs[1], 0.0)

    def test_ecdf_and_lorenz_gini(self):
        from zero2viz.core.stats import ecdf_points, gini, lorenz_points
        ecdf = ecdf_points([10, 20, 20, 40])
        self.assertEqual(ecdf[0], [10.0, 25.0])
        self.assertEqual(ecdf[1], [20.0, 75.0])
        self.assertEqual(ecdf[-1], [40.0, 100.0])

        self.assertAlmostEqual(gini([10, 10, 10, 10]), 0.0, places=6)
        pts, g = lorenz_points([0, 0, 0, 100])
        self.assertEqual(pts[0], [0.0, 0.0])
        self.assertEqual(pts[-1], [100.0, 100.0])
        self.assertAlmostEqual(g, 0.75, places=3)
        self.assertIsNone(gini([-5, 10, 20]))

    def test_new_chart_types_render_across_all_engines(self):
        from zero2viz.engines import engines
        from zero2viz.engines.base import THEMES
        theme = THEMES["Studio Light"]
        specs = [
            {
                "type": "lollipop", "title": "Ranked districts",
                "x_label": "district", "y_label": "score", "stacked": False,
                "theme": theme,
                "data": {"categories": ["Konak", "Bornova", "Buca"],
                         "series": [{"name": "score", "values": [84.0, 91.0, 76.0],
                                     "ids": [[1], [2], [3]]}]},
            },
            {
                "type": "ecdf", "title": "Area ECDF",
                "x_label": "area", "y_label": "cumulative %", "stacked": False,
                "theme": theme,
                "data": {"series": [{"name": "area",
                                     "points": [[10.0, 25.0], [20.0, 60.0], [45.0, 100.0]]}]},
            },
            {
                "type": "lorenz", "title": "Population Lorenz",
                "x_label": "pop", "y_label": "cumulative share (%)", "stacked": False,
                "theme": theme,
                "data": {"series": [{"name": "pop", "gini": 0.425,
                                     "points": [[0.0, 0.0], [50.0, 18.0], [100.0, 100.0]]}]},
            },
        ]
        for spec in specs:
            for eng in engines():
                if not eng.available():
                    continue
                self.assertIn(spec["type"], eng.supports, (eng.id, spec["type"]))
                html = eng.build_html(spec)
                self.assertTrue(html.startswith("<!DOCTYPE html>"), (eng.id, spec["type"]))
                self.assertGreater(len(html), 1000, (eng.id, spec["type"]))


if __name__ == "__main__":
    unittest.main()
