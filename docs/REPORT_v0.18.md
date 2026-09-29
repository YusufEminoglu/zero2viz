# Implementation Report v0.18.0

Delivers `ENHANCEMENT_PLAN_v0.17.md` (small multiples + animated Explore). The
plan was written for v0.17.0, but that number was used by the Print Layout theme
API, so this ships as **v0.18.0**. Committed locally; not tagged, not pushed,
not uploaded.

## 1. Phase status

- Phase 1: DONE: "Facet by" small multiples for bar, line, area, scatter, bubble
  and pie on ECharts and Plotly (`a68ed5c`).
- Phase 2: DONE: "Explore: animate by", one shared play bar for count bars,
  histograms, scatter and the Rows / Complete cards (`dce9543`).
- Phase 3: DONE: architecture, guide, README, changelog, metadata 0.18.0.

## 2. Shortcomings register

| # | Outcome |
|---|---|
| S1 | Facet + animate combined is not built. The two pickers disable each other (tested in real QGIS both ways); the tooltip says to clear one to use the other. |
| S2 | Rule implemented: keep the 12 most populous groups, shown in natural (numeric-aware) order; ties broken by first appearance. Dropped groups are named in the render status (first 5 + count) and counted in the chart subtitle. |
| S3 | Vega-Lite faceting was not attempted: `facets` is empty for Vega-Lite and matplotlib, the picker is disabled for them, and they ignore a `facets` block (tested). |
| S4 | Frames come from values present in the rows, so a frame always has at least one row; the "–" KPI state is a guard for that invariant, not a reachable path today. |
| S5 | **Open.** Only an offscreen capture (QGIS 4.2, Segoe UI registered) exists: both new rows render in line with their neighbours. A real Windows desktop screenshot is still needed, as the plan requires. The changes add form rows only; the tab bar is untouched. |
| S6 | New: stacked facets. ECharts stacks by id across all grids, so stacked panels merged into panel 1 and the rest were empty. Found by the render check, fixed with per-panel stack ids. |
| S7 | New: stacked charts with a fixed axis (existing animation frames as well as facets) took their range from single series, so a stack top could clip. Now the range covers stacked totals. |
| S8 | New: fixed axes ended on raw values ("5,855") with a stray label above the last gridline. Bounds and interval now come from one fit (`_axis_fit`). The errorbar and violin manual screenshots were regenerated and now end on round ticks. |
| S9 | Not fixed (pre-existing): the violin KDE tails extend below zero for strictly positive data (see the manual's population violin). |

## 3. Evidence

- Pure: `tests/test_core.py`, 17 passed (facet grouping, shared axes, stacked
  bounds, per-panel stacks, pinned colours, Plotly subplots, axis fit).
- QGIS 3.44 and 4.2: `tests/smoke_plugin.py`, 10/10 on both. Covers the dock's Facet by
  (panels, whole dataset kept in `data`, mutual exclusion, Vega-Lite disabled)
  and Explore animation (per-frame bar totals and histogram bins against frame
  sizes, per-frame Rows KPI, static tiles stay static).
- Headless Chrome: `scratch/check_02viz_facets.mjs`, 12/12 (every panel must
  hold series-coloured pixels; a mutant with one empty panel fails);
  `check_02viz_anim.mjs` 12/12 (unchanged animation); `check_02viz_explore.mjs`
  PASS (autoplay advances, jumping to the last frame sets the KPI and the live
  bar total to 50 rows, 7/7 tiles painted, zero JS errors).
