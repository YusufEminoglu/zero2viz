# 02viz — Enhancement Plan v0.17.0 (small multiples + animated Explore)

**Plugin:** 02viz — Geospatial Visualization Studio · package/zip-root `zero2viz` · repo `github.com/YusufEminoglu/zero2viz`
**Baseline:** v0.16.0 (verified against the current tree, not the superseded `ENHANCEMENT_PLAN_v0.11.md`, whose five workstreams — custom Vega-Lite spec editor, PNG/SVG/PDF export, Explore tile picker, chart presets, cross-filtering — have all since shipped across v0.13.0–v0.16.0. This plan starts clean from v0.16.0, not from that file's backlog).
**Source:** `docs/ARCHITECTURE.md`'s own "Planned next" line names both items in this plan verbatim: *small-multiples dashboards and animation on Explore tiles*. This plan formalizes those two, not invented scope.
**Deliverable:** one release, **v0.17.0**, implemented, fully tested on BOTH QGIS 3.44 (LTR) and QGIS 4, committed, tagged and pushed. Hub upload stays MANUAL (do not attempt).

---

## 0. Read first (mandatory)

1. Repo root `AGENTS.md` and `RELEASING.md` — monorepo conventions are binding.
2. `zero2viz/docs/ARCHITECTURE.md` (the flow, the spec contract, the animation
   design in `transform.build_frames`/`union_categories`/`align_values` this
   plan extends), `README.md`, `CHANGELOG.md`.
3. **Read the v0.15.1–v0.15.14 changelog entries in full before touching any
   layout/sizing code.** They are not incidental history: eight consecutive
   releases chased the same tab-rendering bug because the project's offscreen
   test harness cannot reproduce real Windows font metrics or the native
   Windows tab theme engine's own internal insets — a fix that passed every
   headless test still shipped visibly broken three times in a row. **Ground
   rule, not a suggestion: any UI change in this plan must be confirmed with
   a real desktop screenshot before being called done. An offscreen/headless
   render passing is necessary but never sufficient evidence for a layout or
   sizing claim in this specific plugin.**
4. The existing test harnesses (extend, never weaken them):
   - `scratch/test_02viz_charts.py`, `scratch/test_02viz_presets.py` — real-QGIS
     engine/e2e suites (run via OSGeo4W `python-qgis-ltr.bat` = QGIS 3.44 and
     `python-qgis.bat` = QGIS 4; **script files only** — multiline `-c`
     silently fails).
   - `scratch/check_02viz_render.mjs`, `scratch/check_02viz_anim.mjs` —
     headless-Chrome render checks (painted-canvas / svg-node asserts, zero
     JS exceptions). Extend `check_02viz_anim.mjs`'s pattern for the new
     small-multiples and animated-Explore output rather than writing a third,
     divergent check script.
   - `scratch/capture_02viz_dock.py` — the established real-widget-capture
     pattern (offscreen QGIS, `_Iface` stub, `widget.grab()`) for verifying
     dock layout: reuse it for this plan's dock changes, but treat its output
     as a first look, not proof — see ground rule 3.
5. Architecture rule for all work below: dock builds a plain-dict **spec** →
   engine `build_html(spec) -> str` returns ONE self-contained offline HTML.
   Everything below must be additive and zero-regression: every one of the
   17 chart types, both diagram/label tabs, presets, and the existing
   animation/cross-filter/export toolbar must keep working exactly as today
   when the new features are left unused.

---

## 1. Baseline facts (verified against the current tree)

- 17 chart types across 4 engines (ECharts, Plotly.js, Vega-Lite, optional
  matplotlib/seaborn); Vega-Lite covers 14 of 17 (treemap/sunburst/radar
  excluded per each engine's own `supports` set — this plan does not touch
  engine chart-type coverage).
- Animation ("Animate by" a field) already works for the main Charts tab via
  `core/transform.build_frames` (`union_categories` for a stable axis,
  `align_values` to re-index each frame, a global value range) — `frames`
  in the spec, per-engine `ANIMATABLE` set (bar/line/area/scatter/bubble/pie
  for ECharts+Plotly; empty for Vega-Lite/matplotlib).
- `core/profile.py::build_profile()` returns `{"title","meta","kpis",
  "insights","tiles":[{"spec","span"}]}` — one static chart spec per tile,
  no faceting, no animation axis. `engines/dashboard.py::build_dashboard()`
  renders that profile into one static HTML page.
- The Explore tile picker (checkable list, `self.tile_picker`) and PNG/SVG/
  PDF/HTML export toolbar already apply to whatever HTML is currently shown
  via `_show_html()`/`self._last_html` — both the single-chart view and an
  Explore dashboard use the same path, so neither needs new export plumbing.
- `custom Vega-Lite spec editor` (`dock.py` line ~1508, "Custom spec JSON
  error at line…") is real and shipped; not touched by this plan.

---

## 2. Ground rules (hard requirements)

1. **100% English** in all code, help, docs. Never use the words "elite",
   "best-in-class", "ultimate" or similar self-praise in any copy.
2. **No dead knobs**: every parameter you declare must change the output.
3. **Determinism**: no unseeded randomness; category/facet ordering must be
   explicit and stable (matches `union_categories`'s existing numeric-aware
   sort convention — years sort 2000, 2001, 2002…, not lexicographically).
4. **No AI attribution** in commits (no `Co-Authored-By:` trailers of any
   kind).
5. **Never weaken an existing test or gate.** If a test asserts a chart-type
   count, an engine's `supports`/`ANIMATABLE` set size, or a tile count, the
   count may only go up. If a gate blocks you, fix the code, not the test.
6. **Zero external Python dependencies**, per the plugin's own hard rule —
   small multiples and Explore animation are pure additions to the existing
   spec/engine/transform pipeline, not a new engine or a new runtime.
7. **Do not bump the version or write the changelog until Phase 3. Do not
   tag, run `release.ps1`, or upload** — the maintainer releases manually
   after reviewing your report.
8. One commit per completed phase, messages like
   `phase-1: add small-multiples faceting to chart spec pipeline`.

---

## Phase 1 — Small-multiples (faceted) charts

**What.** A new "Facet by" field picker in the Charts tab (categorical
fields only, mirroring the existing "Animate by" picker's field-type
filter). When set, the single chart becomes a grid of small repeated
charts — one per distinct value of the facet field — each showing the same
chart type and field bindings, filtered to that facet value, sharing one
consistent axis range and one consistent color/category mapping across the
whole grid (the same stability guarantee `union_categories`/`align_values`
already give animation frames, reused here for facets instead of time
steps).

**Design.**
- `core/transform.py`: add `build_facets(rows, facet_field, chart_type,
  field_bindings) -> list[dict]`, structurally parallel to the existing
  `build_frames` (same union-categories/align-values/global-range approach,
  but producing a *list of simultaneously-shown* small specs instead of a
  *sequence of frames*). Cap the facet count (default 12, matching a
  reasonable grid; report a plain-language truncation notice — highest-count
  categories first — exactly like the existing "first 100,000-row safety
  window" precedent in v0.16.0's provenance messaging) rather than silently
  rendering an unusably large grid.
- Spec contract (`engines/base.py`): add an optional `facets` block,
  structurally parallel to the existing `frames` block, so engines that
  don't support it simply ignore it and render `spec["data"]` as today —
  the same graceful-degradation pattern animation already uses per engine.
- Engine support: implement for ECharts and Plotly first (both have native
  subplot-grid primitives); Vega-Lite has a native `facet` operator and may
  be straightforward to add in the same phase — attempt it, but do not let
  it block ECharts/Plotly landing if its layered-spec `scale: null` gotcha
  (already documented in ARCHITECTURE.md) turns out to interact badly with
  facets; matplotlib may be skipped (`FACETABLE` empty set) since it's the
  optional static-image engine.
- UI: reuse the existing per-tab card layout conventions; do not introduce
  a new visual language for one picker.

**Interaction with animation:** facet and animate are mutually exclusive in
this phase (disable "Animate by" while "Facet by" is set, and vice versa,
with a plain status message explaining why) — a faceted *and* animated grid
is a real technique but a materially bigger scope; ship the simpler,
independently-useful version first and record the combined case as a
deferred shortcoming (S-register below), not a silent limitation.

---

## Phase 2 — Animation on Explore tiles

**What.** An "Animate by" field picker in the Explore panel (alongside the
existing tile picker and "Selected features only" checkbox). When set,
every chartable tile in the profile animates over that field's ordered
values using the exact same frame-building path the Charts tab already
uses — KPI tiles that are themselves numeric summaries update per frame
alongside the charts, so the whole dashboard moves together rather than
some tiles animating and others staying static.

**Design.**
- `core/profile.py::build_profile()`: accept an optional `animate_by`
  parameter; when set, compute per-frame values for every applicable tile
  spec using `transform.build_frames` (reused, not reimplemented) and for
  the KPI numbers (a new small helper, since KPIs are scalars rather than
  chart specs — each KPI becomes a `{value_per_frame: [...]}` the dashboard
  template steps through in lockstep with the chart frames).
- `engines/dashboard.py::build_dashboard()`: when the profile carries frame
  data, emit one shared play-axis control (slider + play/pause) driving
  every animatable tile and the KPI numbers simultaneously — do not give
  each tile its own independent timeline; a dashboard where tiles animate
  out of sync with each other is confusing, not useful.
- Tiles built from non-animatable chart types (see the existing per-engine
  `ANIMATABLE` sets) or from categorical/insight content that has no
  natural per-frame value simply render their frame-0 (static) content for
  the whole animation, exactly like a non-animatable chart type already
  does in the main Charts tab today — no new special-casing needed, reuse
  the existing fallback.

---

## Phase 3 — Documentation, version bump, changelog

Only after Phases 1–2 are done and tested:
- Update `docs/ARCHITECTURE.md`: move "small-multiples dashboards and
  animation on Explore tiles" out of "Planned next" and into the dated
  version-history table/prose the doc already uses for shipped features
  (e.g. the "Animation (play axis) — v0.9.0" section pattern), and document
  the new `facets` spec block and `build_facets`/`animate_by` contracts at
  the same level of detail as the existing `frames` documentation.
- Update `README.md`'s feature list and `CHANGELOG.md` with a new
  `## [0.17.0]` entry.
- Bump `metadata.txt`'s `version=0.17.0`.
- Do **not** tag, run `release.ps1`, or upload — stop after committing and
  hand the report to the maintainer.

---

## Known shortcomings register (fix or explicitly defer with reason)

| # | Shortcoming | Severity | Phase |
|---|---|---|---|
| S1 | Facet + animate combined (a faceted grid where each small chart also plays through time) is out of scope for this plan — confirm it is disabled with a clear message, not silently ignored | Medium | 1 |
| S2 | A facet field with more distinct values than the grid cap needs a truncation notice that names which categories were dropped and why (highest-count-first is a starting rule, not a mandate — document whatever rule is actually implemented) | Medium | 1 |
| S3 | Vega-Lite faceting may hit the documented layered-spec `scale: null` crash; if so, ship Vega-Lite without facet support (`FACETABLE` excludes it) rather than a half-working facet grid, and say so explicitly in the report | Low | 1 |
| S4 | KPI-tile per-frame values need a clear empty/undefined state for a frame where the underlying rows are empty (e.g. a facet-by-year field with a gap year) — must not render a stale or misleading number | Medium | 2 |
| S5 | Per ground rule 3 in §0: every layout change here must ship with a real desktop screenshot in the report, not just an offscreen-harness pass — do not repeat the v0.15.1–v0.15.14 pattern | High | 1, 2 |

---

## R. Required response format

Deliver a single file `REPORT_v0.17.md` in the plugin root:

```markdown
# Implementation Report v0.17.0
## 1. Phase status
Phase 1: DONE|PARTIAL — <one line>
Phase 2: DONE|PARTIAL — <one line>
Phase 3: DONE|PARTIAL — <one line>
## 2. Shortcomings register outcomes
S1–S5, plus any NEW shortcomings discovered, numbered S6+
## 3. Real screenshot evidence (mandatory per ground rule 3)
(embed or attach real desktop captures of: a faceted chart grid at 2–3
grid sizes, an animated Explore dashboard mid-playback, on BOTH QGIS 3.44
and QGIS 4 — offscreen-only captures do not satisfy this section)
## 4. Test evidence
### 4.1 pure test output (verbatim, complete)
### 4.2 e2e QGIS 3.44 LTR output (verbatim, complete)
### 4.3 e2e QGIS 4.x output (verbatim, complete)
### 4.4 check_02viz_render.mjs / check_02viz_anim.mjs output (verbatim)
## 5. Deviations from this plan
## 6. Commit list
(hash + message, one per line)
```

**Honesty over completeness:** a PARTIAL with truthful evidence is
acceptable; a DONE that the reviewer's re-run contradicts invalidates the
delivery.
