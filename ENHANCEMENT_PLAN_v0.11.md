# 02viz — Enhancement Plan v0.11.0 (single phase)

**Plugin:** 02viz — Geospatial Visualization Studio · package/zip-root `zero2viz` · repo `github.com/YusufEminoglu/zero2viz`
**Baseline:** v0.10.2 (commit `19e7ef2`, main). Working tree already contains an **uncommitted new icon** (`icons/icon.png`) — include it in this release, do not regenerate it.
**Deliverable:** one release, **v0.11.0**, implemented, fully tested on BOTH QGIS 3.44 (LTR) and QGIS 4, committed, tagged and pushed. Hub upload stays MANUAL (do not attempt).

---

## 0. Read first (mandatory)

1. Repo root `AGENTS.md` and `RELEASING.md` — monorepo conventions are binding.
2. `zero2viz/docs/ARCHITECTURE.md`, `zero2viz/README.md`, `zero2viz/CHANGELOG.md`.
3. The existing test harnesses (you will extend, never weaken them):
   - `scratch/test_02viz_charts.py` — real-QGIS engine/e2e suite (run via OSGeo4W `python-qgis-ltr.bat` = QGIS 3.44 and `python-qgis.bat` = QGIS 4; **script files only** — multiline `-c` silently fails).
   - `scratch/check_02viz_render.mjs` + `scratch/check_02viz_anim.mjs` — headless-Chrome render checks (painted-canvas / svg-node asserts, zero JS exceptions).
   - `scratch/verify_02viz_v0_10.py` — pattern for pure-module + offscreen dock-UI verification.

---

## 1. Phase scope — five workstreams, one release

Architecture rule for all of them: dock builds a plain-dict **spec** → engine `build_html(spec) -> str` returns ONE self-contained offline HTML. Everything below must be additive and zero-regression.

### W1 — Custom Vega-Lite spec editor
- New Charts-tab affordance (e.g. "⟨/⟩ Custom spec" toggle or engine-gated button, visible only when engine = Vega-Lite): a plain-text editor pre-filled with the spec the current controls generate (`engines/vegalite.py` already builds VL specs — expose that as the designed `vl_spec()` entry point).
- User edits JSON → Render validates (pure-Python `json.loads` + minimal schema sanity: has `mark` or `layer`/`concat`) → engine wraps the user spec with the vendored vega/vega-lite runtime and the data injected as a named dataset. Parse errors surface in the panel, never a silent blank.
- Keep the title-transport selection bridge working when the user spec keeps the `ids`-carrying data; degrade gracefully (no crash) when it doesn't.
- **Known VL trap:** in a LAYERED spec, a color channel with `scale: null` crashes cross-layer scale merge — use filtered fixed-colour layers instead.

### W2 — SVG / PDF export
- Beside "Export HTML": **Export SVG** and **Export PNG** for all engines where feasible; **PDF** via QGIS's own `QPrinter`/`QPdfWriter` from the rendered view when a web view exists, else from the matplotlib figure.
  - ECharts: `chartInstance.getDataURL({type:'svg'})` requires the SVG renderer — either initialise with `renderer:'svg'` for export builds, or render an export-only page. PNG via existing toolbox `saveAsImage` remains.
  - Vega-Lite: `view.toSVG()` / `view.toImageURL('png')`.
  - Plotly: `Plotly.toImage(gd, {format:'svg'})`.
  - matplotlib: native `savefig` svg/pdf/png — the easy path; wire it first.
- Headless capture path: reuse the Chrome CDP pattern from `check_02viz_render.mjs` only for tests; in-QGIS export must not require Chrome. If an engine/backend combination can't do SVG in-process (QtWebKit!), grey the option and say why (follow the v0.9.2 `webkit_ok` explainer pattern).

### W3 — Explore dashboard tile picker + dashboard polish
- Explore currently renders a fixed set of tiles. Add a lightweight picker (checkable list or ⚙ popup in the dock, state remembered per session) for: KPI row, field table, count bars, histograms, corr matrix, scatter+trend, normalised box plot, insights.
- `core/profile.py` gets a `sections=` filter parameter (pure, headless-testable); `engines/dashboard.py` renders only requested sections. Defaults = today's output (zero regression; `insights[0]` must stay "Strongest link" — an existing test depends on it).

### W4 — Cross-filter completion
- Extend map→chart / chart→map linkage to the surfaces that still lack it: line/area point symbols and treemap/sunburst nodes (requires ids flowing through `transform.tree_rows` — add them). Same title-transport bridge (`document.title="o2viz-select:<ids>:<seq>"`); NEVER use `addToJavaScriptWindowObject` on the WebKit path (crashes QGIS 3.44) and no QWebChannel (WebEngine-only).

### W5 — Icon + docs + gallery refresh
- Commit the new `icons/icon.png` (already in the working tree).
- README: refresh feature list for W1–W4, add/refresh screenshots in `docs/` (generate via the existing sample-page + Chrome screenshot pattern; eyeball them).
- Update the built-in Guide (`engines/guide.py`) with new sections for custom specs, exports and the tile picker. **Bandit B608 trap:** keep the big static guide body a PLAIN (non-f) module constant; putting "select…from" wording inside one big f-string trips a phantom-SQL Critical and the Hub scanner hard-blocks Criticals.
- `metadata.txt` + `CHANGELOG.md` + About box → 0.11.0. Fix the misplaced `[0.10.2]` entry currently sitting ABOVE the changelog intro lines.

Cut scope if needed in this order: W3 picker persistence → W2 PDF → W1 bridge-through-custom-spec. Never cut tests.

---

## 2. Hard rules (violating any = failed phase)

1. **No `Co-Authored-By: Claude`** (or any AI attribution) in any commit/tag.
2. **No literal `%` in `metadata.txt`** — Hub INI interpolation breaks; grep before release.
3. **No "elite/best/ultimate" wording** in any user-facing copy.
4. Offline & zero-dependency stays: no network calls, no new mandatory Python deps (matplotlib remains the only opt-in), vendored JS only (record exact version + license).
5. QtWebKit path must never silently blank: respect/extend `ChartEngine.webkit_ok` + fallback explainer pages.
6. English UI and English CHANGELOG throughout.
7. Do not weaken or delete any existing test assertion; counts may only go up.
8. Package/zip root stays `zero2viz` (PEP 8 identifier — Hub hard-blocks digit-first names); display name stays `02viz - Geospatial Visualization Studio`.
9. Vendored bundles are inlined into the HTML → never substring-scan whole pages for feature markers in tests; parse the embedded OPT/FIG/spec objects.
10. Dock QSS must pin text/field/combo-popup colours, not just backgrounds (Qt6 dark-palette bleed; `QComboBox QAbstractItemView` is the black surface). Offscreen platform hides this bug — test dark via a forced dark Fusion palette (see `scratch/capture_02viz_dock.py`).

## 3. Quality gates (all must pass on BOTH QGIS 3.44 and QGIS 4 before release)

- `scratch/test_02viz_charts.py` — extend with W1/W2/W3/W4 coverage; ALL PASS.
- `scratch/check_02viz_render.mjs` + `check_02viz_anim.mjs` — ALL PASS, zero JS exceptions; add pages for custom-spec render and cross-filter on treemap/line.
- New offscreen dock-UI checks for the spec editor, export buttons, tile picker (pattern: `verify_02viz_v0_10.py` PART D — fake iface, no web view creation offscreen).
- Static: `packaging/validate_plugin.py` 0 warnings · `flake8` 0 · `bandit -r zero2viz` 0 High/Med (Hub runs Bandit/detect-secrets/Flake8 and hard-blocks Criticals) · `py_compile` all files.
- Eyeball: generate sample pages/screenshots for every new surface and actually look at them.

## 4. Release procedure (v0.11.0)

1. Pre-bump `metadata.txt` + `CHANGELOG.md` yourself during the work. **Therefore SKIP `release.ps1`'s bump step** (its `bump_version.py` prepends unconditionally → duplicate stub). Run its remaining steps by hand, exactly like v0.9.1/v0.9.2:
2. `packaging/validate_plugin.py` → `Build-PluginZip.ps1` (verify version inside zip = 0.11.0, single root `zero2viz/`).
3. `git add -A && git commit -m "Release v0.11.0" && git tag v0.11.0 && git push origin HEAD && git push origin v0.11.0`.
4. GitHub Release v0.11.0 with the built `zero2viz.zip` attached as asset (GitHub's auto source zip has the wrong root and is NOT QGIS-installable).
5. Hub upload: **do NOT attempt** — report "ready for manual Hub upload" instead.

## 5. Definition of done

All five workstreams (or documented, justified cuts per §1's cut order) shipped; every gate in §3 green on both QGIS versions; release steps §4 completed and pushed; final report lists: what shipped, test counts before/after, gate outputs, anything cut and why.
