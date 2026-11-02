# -*- coding: utf-8 -*-
"""Matplotlib engine — optional, publication-grade *static* charts.

Unlike the vendored JS engines, this renders the spec to a static figure with
matplotlib (a seaborn-style "whitegrid" look) and embeds it as a base64 PNG in
the same HTML shell, so the dock viewer and one-file export work unchanged.
The page also carries the figure as SVG (``savefig(format="svg")``) for
``window.o2vizExport``. The trade-off is no chart→map interactivity — this is
the print/publication path.

No global matplotlib state is touched: every figure is a
``matplotlib.figure.Figure`` with its own ``FigureCanvasAgg``, drawn inside
``matplotlib.rc_context``. The process backend, ``rcParams`` and pyplot's
figure registry (the QGIS Python console, other plugins) stay exactly as they
were.

matplotlib ships with the QGIS Python on OSGeo4W and the standalone
installers; when it is missing, the engine reports unavailable and the dock
shows the command to install it (see ``core.requirements``). The import is
lazy so it never slows QGIS startup.
"""
from __future__ import annotations

import base64
import io

from ..core import requirements
from .base import (FACETABLE, ChartEngine, category_colors, colors_for, escape_html,
                   is_horizontal, options_of, page_title, script_json, theme_of)

# the subset matplotlib draws cleanly from the existing spec; the dock
# greys out the rest for this engine (treemap/sunburst/radar/error*)
_SUPPORTED = frozenset({
    "bar", "lollipop", "line", "area", "scatter", "bubble", "histogram",
    "pie", "box", "heatmap", "density", "violin", "pareto", "ecdf", "lorenz",
})

# chart types that carry reference lines/bands on their value axis (core.overlays)
_OVERLAY_OK = frozenset(("bar", "lollipop", "line", "area", "scatter", "bubble"))

# category charts: one tick label (and usually one patch) per category.
# 100,000 bars blocked QGIS for minutes, so at most MAX_CATEGORIES are drawn
# and the figure says so.
_CATEGORY_KINDS = frozenset(("bar", "lollipop", "line", "area", "histogram", "pareto"))
MAX_CATEGORIES = 300
# scatter collections larger than this are rasterised inside the SVG so the
# vector export stays small (axes, labels and text remain vectors)
_RASTER_POINTS = 5000

# seaborn's "whitegrid" style + "notebook" context, as plain rcParams, so the
# look does not depend on importing seaborn (whose set_theme() rewrites the
# process-wide rcParams)
_STYLE = {
    "axes.facecolor": "white", "axes.edgecolor": ".8", "axes.grid": True,
    "axes.axisbelow": True, "axes.labelcolor": ".15", "figure.facecolor": "white",
    "grid.color": ".8", "grid.linestyle": "-", "text.color": ".15",
    "xtick.color": ".15", "ytick.color": ".15", "xtick.direction": "out",
    "ytick.direction": "out", "lines.solid_capstyle": "round",
    "patch.edgecolor": "w", "patch.force_edgecolor": True,
    "xtick.bottom": False, "ytick.left": False,
    "font.size": 12, "axes.labelsize": 12, "axes.titlesize": 12,
    "xtick.labelsize": 11, "ytick.labelsize": 11, "legend.fontsize": 11,
    "axes.linewidth": 1.25, "grid.linewidth": 1, "lines.linewidth": 1.5,
    "lines.markersize": 6, "patch.linewidth": 1,
    "font.family": ["sans-serif"],
    "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial", "Liberation Sans",
                        "sans-serif"],
    "svg.fonttype": "path",
}

_IMG_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  html, body {{ margin: 0; width: 100%; height: 100%; background: {bg};
               display: flex; align-items: center; justify-content: center; }}
  img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
</style></head>
<body>
<img id="o2vizImage" alt="{title}" src="data:image/png;base64,{b64}"/>
<script>
  // static image — keep the dock's bridge calls inert and mark ready
  window.__o2vizSelect = function () {{}};
  window.__o2vizHighlight = function () {{}};
  window.__o2vizFacetCount = {facets};
  window.__o2vizNote = {note};
  var O2VIZ_SVG = {svg};
  var O2VIZ_BG = {bg_json};
  // window.o2vizExport (engines.base contract): the matplotlib figure saved
  // as SVG (savefig), sized to width x height (aspect kept); PNG rasterises
  // that vector at the requested size.
  function __o2vizSizedSvg(w, h) {{
    var doc = new DOMParser().parseFromString(O2VIZ_SVG, "image/svg+xml");
    var root = doc.documentElement;
    root.setAttribute("width", String(w));
    root.setAttribute("height", String(h));
    root.setAttribute("preserveAspectRatio", "xMidYMid meet");
    return new XMLSerializer().serializeToString(root);
  }}
  window.o2vizExport = function (format, width, height, scale) {{
    return new Promise(function (resolve, reject) {{
      try {{
        var w = Math.max(16, Math.round(width || 900));
        var h = Math.max(16, Math.round(height || 560));
        if (format === "svg") {{ resolve(__o2vizSizedSvg(w, h)); return; }}
        if (format !== "png") {{ throw new Error("Unsupported export format: " + format); }}
        var s = scale || 1;
        var canvas = document.createElement("canvas");
        canvas.width = Math.round(w * s);
        canvas.height = Math.round(h * s);
        var ctx = canvas.getContext("2d");
        ctx.fillStyle = O2VIZ_BG;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        var img = new Image();
        img.onload = function () {{
          try {{
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL("image/png"));
          }} catch (e) {{
            // a browser that taints canvases with SVG: scale the PNG instead
            var png = document.getElementById("o2vizImage");
            var k = Math.min(canvas.width / png.naturalWidth, canvas.height / png.naturalHeight);
            var c2 = document.createElement("canvas");
            c2.width = canvas.width; c2.height = canvas.height;
            var x2 = c2.getContext("2d");
            x2.fillStyle = O2VIZ_BG; x2.fillRect(0, 0, c2.width, c2.height);
            x2.drawImage(png, (c2.width - png.naturalWidth * k) / 2,
                         (c2.height - png.naturalHeight * k) / 2,
                         png.naturalWidth * k, png.naturalHeight * k);
            resolve(c2.toDataURL("image/png"));
          }}
        }};
        img.onerror = function () {{ reject(new Error("The chart image could not be drawn")); }};
        img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(__o2vizSizedSvg(w, h));
      }} catch (e) {{ reject(e); }}
    }});
  }};
  window.__chartReady = true;
</script>
</body></html>
"""


def _nan(values, np):
    """Values as floats with None → NaN (a gap, never a zero)."""
    return np.array([np.nan if v is None else v for v in values], dtype=float)


class MatplotlibEngine(ChartEngine):
    id = "matplotlib"
    label = "Matplotlib / seaborn"
    supports = _SUPPORTED
    facets = FACETABLE
    MAX_CATEGORIES = MAX_CATEGORIES

    def __init__(self):
        self.last_note = ""

    @classmethod
    def available(cls) -> bool:
        return requirements.library_available("matplotlib")

    def build_html(self, spec: dict) -> str:
        if not self.available():
            raise RuntimeError(
                "matplotlib is not installed in this QGIS Python")
        png, svg, note = self._render(spec, ("png", "svg"))
        self.last_note = note
        theme = theme_of(spec)
        fac = spec.get("facets") if spec.get("type") in self.facets else None
        n_facets = len(fac.get("datas", [])) if isinstance(fac, dict) else 0
        bg = theme.get("bg", "#ffffff")
        return _IMG_HTML.format(title=escape_html(page_title(spec.get("title", "02viz chart"),
                                                             fallback="chart")),
                                bg=escape_html(bg), bg_json=script_json(bg),
                                b64=base64.b64encode(png).decode("ascii"),
                                svg=script_json(svg.decode("utf-8")),
                                note=script_json(note), facets=n_facets)

    def render(self, spec: dict, fmt: str = "png", width: int | None = None,
               height: int | None = None) -> bytes:
        """Public: the chart as PNG or SVG bytes straight from ``savefig`` —
        at ``width`` x ``height`` pixels (100 px per inch) when given, else at
        the default figure size with a tight bounding box."""
        if fmt not in ("png", "svg"):
            raise ValueError(f"Unsupported format: {fmt}")
        return self._render(spec, (fmt,), width, height)[0]

    # ───────────────────── figure builder ─────────────────────

    def _render(self, spec: dict, formats: tuple, width: int | None = None,
                height: int | None = None):
        """→ (bytes per requested format..., note). One figure, saved once
        per format, entirely inside rc_context (no global state)."""
        import matplotlib
        import numpy as np
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        kind = spec["type"]
        theme = theme_of(spec)
        palette = theme["palette"] or ["#2a8f85"]
        notes: list[str] = []

        def col(i):
            return palette[i % len(palette)]

        sized = bool(width and height)
        size = ((max(1, int(width)) / 100.0, max(1, int(height)) / 100.0) if sized else None)

        def new_figure(figsize, dpi):
            fig = Figure(figsize=figsize, dpi=dpi)
            FigureCanvasAgg(fig)  # the figure's own canvas: no pyplot, no backend switch
            return fig

        with matplotlib.rc_context(_STYLE):
            if spec.get("facets") and kind in self.facets:
                fig = self._facet_figure(spec, new_figure, np, col, palette, theme, notes, size)
            else:
                fig = new_figure(size or (8.2, 5.0), 100 if sized else 150)
                ax = fig.add_subplot(111)
                fig.patch.set_facecolor(theme["bg"])
                ax.set_facecolor(theme["bg"])
                self._draw(kind, ax, spec.get("data", {}), spec, np, col, palette, theme, notes)
                self._style_axes(ax, theme, kind, spec)
                if spec.get("overlays") and kind in _OVERLAY_OK:
                    self._draw_overlays(ax, spec["overlays"], is_horizontal(spec))
                self._orient_axes(ax, kind, spec)
                if spec.get("title"):
                    ax.set_title(spec["title"], color=theme["text"], fontsize=15,
                                 fontweight="bold")
            note = "; ".join(dict.fromkeys(notes))
            if note:
                fig.text(0.01, 0.005, note, fontsize=8, color=theme["text"], alpha=0.85,
                         ha="left", va="bottom")
            if sized:
                fig.tight_layout()
            out = []
            for fmt in formats:
                buf = io.BytesIO()
                kw = {"format": fmt, "facecolor": fig.get_facecolor()}
                if sized:
                    kw["dpi"] = 100
                else:
                    kw.update(dpi=150, bbox_inches="tight")
                fig.savefig(buf, **kw)
                out.append(buf.getvalue())
        return (*out, note)

    def _facet_figure(self, spec: dict, new_figure, np, col, palette, theme: dict, notes: list,
                      size=None):
        """Small multiples onto a shared-scale subplot grid."""
        fac = spec["facets"]
        kind = spec["type"]
        datas = fac.get("datas", [])
        labels = [str(v) for v in fac.get("labels", [])]
        n = len(datas)
        cols = max(1, min(n, int(fac.get("columns") or 2)))
        rows = -(-n // cols)
        bg, text = theme["bg"], theme["text"]
        bounds = fac.get("bounds") or {}
        static = {k: v for k, v in spec.items() if k != "facets"}
        horizontal = is_horizontal(spec)

        fig = new_figure(size or (max(8.2, cols * 3.1), max(4.6, rows * 2.5)),
                         100 if size else 150)
        axes = fig.subplots(rows, cols, squeeze=False)
        fig.patch.set_facecolor(bg)
        for i in range(rows * cols):
            r, c = divmod(i, cols)
            ax = axes[r][c]
            ax.set_facecolor(bg)
            if i >= n:
                ax.set_visible(False)
                continue
            panel_spec = dict(static, data=datas[i])
            self._draw(kind, ax, datas[i], panel_spec, np, col, palette, theme, notes)
            self._style_axes(ax, theme, kind, spec)
            if kind != "pie" and bounds.get("y"):
                lo, hi = bounds["y"]
                if kind in ("bar", "lollipop", "area"):
                    lo = min(0.0, lo)
                span = (hi - lo) or 1.0
                if horizontal:
                    ax.set_xlim(lo, hi + span * 0.06)
                else:
                    ax.set_ylim(lo, hi + span * 0.06)
            if kind in ("scatter", "bubble") and bounds.get("x"):
                xlo, xhi = bounds["x"]
                xspan = (xhi - xlo) or 1.0
                ax.set_xlim(xlo - xspan * 0.05, xhi + xspan * 0.05)
            self._orient_axes(ax, kind, spec)
            if i + cols < n:
                ax.set_xlabel("")
            if c != 0:
                ax.set_ylabel("")
            ax.set_title(labels[i] if i < len(labels) else "",
                         color=text, fontsize=10.5, fontweight="bold")
        if spec.get("title"):
            fig.suptitle(spec["title"], color=text, fontsize=14, fontweight="bold")
        fig.tight_layout()
        return fig

    @staticmethod
    def _orient_axes(ax, kind: str, spec: dict) -> None:
        """First category on top for horizontal bars; reversed axes on request."""
        if kind == "pie":
            return
        opts = options_of(spec)
        flip_y = is_horizontal(spec) != bool(opts.get("reverse_y"))
        if flip_y:
            ax.invert_yaxis()
        if opts.get("reverse_x"):
            ax.invert_xaxis()

    def _style_axes(self, ax, theme, kind, spec=None) -> None:
        text, grid = theme["text"], theme["grid"]
        ax.tick_params(colors=text, labelsize=9)
        ax.xaxis.label.set_color(text)
        ax.yaxis.label.set_color(text)
        for spine in ax.spines.values():
            spine.set_color(grid)
        if kind not in ("pie", "heatmap"):
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.grid(False)
            value_axis = "x" if (spec is not None and is_horizontal(spec)) else "y"
            ax.grid(True, axis=value_axis, color=grid, linestyle="--", alpha=0.6)
            ax.set_axisbelow(True)

    def _draw(self, kind, ax, data, spec, np, col, palette, theme, notes) -> None:
        text = theme["text"]
        xlab, ylab = spec.get("x_label", ""), spec.get("y_label", "")
        cmap = category_colors(spec)
        horizontal = is_horizontal(spec)

        def cat_series():
            cats = list(data.get("categories", []))
            series = data.get("series") or [{"name": ylab or "value",
                                             "values": data.get("values", [])}]
            if len(cats) > MAX_CATEGORIES:
                notes.append(f"Showing the first {MAX_CATEGORIES:,} of {len(cats):,} "
                             f"categories (the matplotlib limit); use Top N to choose them")
                cats = cats[:MAX_CATEGORIES]
                series = [dict(s, values=list(s.get("values", []))[:MAX_CATEGORIES])
                          for s in series]
            return cats, series

        def series_color(si, name):
            return cmap.get(str(name)) or col(si)

        def cat_axis(positions, cats, value_label, cat_label):
            if horizontal:
                ax.set_yticks(positions)
                ax.set_yticklabels(cats)
                ax.set_ylabel(cat_label)
                ax.set_xlabel(value_label)
            else:
                ax.set_xticks(positions)
                ax.set_xticklabels(cats, rotation=30, ha="right")
                ax.set_xlabel(cat_label)
                ax.set_ylabel(value_label)

        def bars(pos, values, width, **kw):
            if horizontal:
                left = kw.pop("bottom", None)
                return ax.barh(pos, values, height=width, left=left, **kw)
            return ax.bar(pos, values, width, **kw)

        if kind in ("bar", "histogram"):
            cats, series = cat_series()
            xi = np.arange(len(cats))
            if kind == "histogram" or len(series) == 1:
                colors = (colors_for(cats, palette, cmap, single=col(0))
                          if (cmap and kind == "bar") else col(0))
                bars(xi, _nan(series[0]["values"], np), 0.86, color=colors)
            elif spec.get("stacked"):
                bottom = np.zeros(len(cats))
                for si, s in enumerate(series):
                    v = np.nan_to_num(_nan(s["values"], np))
                    bars(xi, v, 0.8, bottom=bottom, color=series_color(si, s["name"]),
                         label=s["name"])
                    bottom += v
            else:
                w = 0.8 / max(1, len(series))
                for si, s in enumerate(series):
                    bars(xi - 0.4 + w * (si + 0.5), _nan(s["values"], np), w,
                         color=series_color(si, s["name"]), label=s["name"])
            cat_axis(xi, cats, "count" if kind == "histogram" else ylab, xlab)
            if len(series) > 1:
                self._legend(ax, theme)

        elif kind == "lollipop":
            cats, series = cat_series()
            xi = np.arange(len(cats))
            w = 0.65 / max(1, len(series))
            for si, s in enumerate(series):
                offset = 0.0 if len(series) == 1 else (-0.325 + w * (si + 0.5))
                pos = xi + offset
                vals = _nan(s["values"], np)
                if len(series) == 1 and cmap:
                    c = colors_for(cats, palette, cmap, single=col(0))
                else:
                    c = series_color(si, s["name"])
                if horizontal:
                    ax.hlines(pos, 0.0, vals, color=c, linewidth=2.2, alpha=0.82)
                    ax.scatter(vals, pos, color=c, s=58, zorder=3,
                               edgecolors=theme["bg"], linewidths=1.2, label=s["name"])
                else:
                    ax.vlines(pos, 0.0, vals, color=c, linewidth=2.2, alpha=0.82)
                    ax.scatter(pos, vals, color=c, s=58, zorder=3,
                               edgecolors=theme["bg"], linewidths=1.2, label=s["name"])
            if horizontal:
                ax.axvline(0.0, color=theme["grid"], linewidth=1.0)
            else:
                ax.axhline(0.0, color=theme["grid"], linewidth=1.0)
            cat_axis(xi, cats, ylab, xlab)
            if len(series) > 1:
                self._legend(ax, theme)

        elif kind in ("line", "area"):
            cats, series = cat_series()
            xi = np.arange(len(cats))
            for si, s in enumerate(series):
                vals = _nan(s["values"], np)
                c = series_color(si, s["name"])
                ax.plot(xi, vals, marker="o", color=c, label=s["name"], linewidth=2.4)
                if kind == "area":
                    ax.fill_between(xi, np.nan_to_num(vals), color=c, alpha=0.3)
            cat_axis(xi, cats, ylab, xlab)
            if len(series) > 1:
                self._legend(ax, theme)

        elif kind in ("scatter", "bubble"):
            for si, s in enumerate(data.get("series", [])):
                pts = s.get("points", [])
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                sizes = [(p[2] ** 2 if len(p) > 2 and p[2] else 42) for p in pts]
                ax.scatter(xs, ys, s=sizes, color=series_color(si, s.get("name", "")),
                           alpha=0.75, edgecolors="none", label=s.get("name", ""),
                           rasterized=len(pts) > _RASTER_POINTS)
            trend = data.get("trend")
            if trend:
                ax.plot([trend[0][0], trend[1][0]], [trend[0][1], trend[1][1]],
                        "--", color=col(2), linewidth=2)
            ax.set_xlabel(xlab)
            ax.set_ylabel(ylab)
            if len([s for s in data.get("series", []) if s.get("name")]) > 1:
                self._legend(ax, theme)

        elif kind == "pie":
            cats = data.get("categories", [])
            ax.pie(data.get("values", []), labels=cats,
                   colors=colors_for(cats, palette, cmap),
                   textprops={"color": text}, wedgeprops={"width": 0.55})
            ax.axis("equal")

        elif kind == "box":
            groups = data.get("groups", [])
            stats = data.get("stats", [])
            bxp = [{"med": s[2], "q1": s[1], "q3": s[3],
                    "whislo": s[0], "whishi": s[4], "label": g}
                   for g, s in zip(groups, stats)]
            box = ax.bxp(bxp, showfliers=False, patch_artist=True)
            box_colors = colors_for(groups, palette, cmap)
            for i, patch in enumerate(box["boxes"]):
                patch.set_facecolor(box_colors[i] if i < len(box_colors) else col(i))
                patch.set_alpha(0.75)
            ax.set_ylabel(ylab)
            ax.tick_params(axis="x", rotation=30)

        elif kind == "heatmap":
            x_cats = data.get("x_cats", [])
            y_cats = data.get("y_cats", [])
            Z = np.full((len(y_cats), len(x_cats)), np.nan)
            for xi_, yi_, v in data.get("cells", []):
                Z[yi_][xi_] = np.nan if v is None else v
            cmap_name = "RdBu_r" if data.get("diverging") else "viridis"
            im = ax.imshow(Z, cmap=cmap_name, aspect="auto")
            ax.set_xticks(np.arange(len(x_cats)))
            ax.set_xticklabels(x_cats, rotation=30, ha="right")
            ax.set_yticks(np.arange(len(y_cats)))
            ax.set_yticklabels(y_cats)
            ax.set_xlabel(xlab)
            ax.set_ylabel(ylab)
            cbar = ax.figure.colorbar(im, ax=ax)
            cbar.ax.tick_params(colors=theme["text"])

        elif kind == "density":
            for si, s in enumerate(data.get("series", [])):
                pts = s.get("points", [])
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                c = series_color(si, s.get("name", ""))
                ax.plot(xs, ys, color=c, label=s.get("name", ""), linewidth=2)
                ax.fill_between(xs, ys, color=c, alpha=0.3)
            ax.set_xlabel(xlab)
            ax.set_ylabel("density")
            if len(data.get("series", [])) > 1:
                self._legend(ax, theme)

        elif kind == "violin":
            groups = data.get("groups", [])
            vcolors = colors_for(groups, palette, cmap)
            for i, poly in enumerate(data.get("polygons", [])):
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                ax.fill(xs, ys, color=vcolors[i] if i < len(vcolors) else col(i), alpha=0.6)
            meds = data.get("medians", [])
            ax.scatter(range(len(meds)), meds, color=theme["text"], zorder=3, s=24)
            ax.set_xticks(range(len(groups)))
            ax.set_xticklabels(groups, rotation=30, ha="right")
            ax.set_ylabel(ylab)

        elif kind == "pareto":
            cats, series = cat_series()
            vals = series[0]["values"]
            cum = list(data.get("cum", []))[:len(cats)]
            xi = np.arange(len(cats))
            ax.bar(xi, _nan(vals, np),
                   color=colors_for(cats, palette, cmap, single=col(0)) if cmap else col(0),
                   width=0.82)
            ax.set_xticks(xi)
            ax.set_xticklabels(cats, rotation=30, ha="right")
            ax.set_xlabel(xlab)
            ax.set_ylabel(ylab)
            ax2 = ax.twinx()
            ax2.plot(xi, cum, color=col(2), marker="o", linewidth=2.2)
            ax2.set_ylim(0, 105)
            ax2.set_ylabel("cumulative %", color=text)
            ax2.tick_params(colors=text, labelsize=9)
            ax2.spines["top"].set_visible(False)

        elif kind == "ecdf":
            for si, s in enumerate(data.get("series", [])):
                pts = s.get("points", [])
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                ax.step(xs, ys, where="post", color=series_color(si, s.get("name", "")),
                        label=s.get("name", ""), linewidth=2.2)
            ax.set_ylim(0, 102)
            ax.set_xlabel(xlab)
            ax.set_ylabel("cumulative %")
            if len(data.get("series", [])) > 1:
                self._legend(ax, theme)

        elif kind == "lorenz":
            ax.plot([0, 100], [0, 100], "--", color=text, alpha=0.45,
                    linewidth=1.5, label="equality (G = 0)")
            series_in = data.get("series", [])
            for si, s in enumerate(series_in):
                pts = s.get("points", [])
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                g = s.get("gini", 0.0)
                lbl = f"{s.get('name', '')} (Gini = {g:.3f})"
                c = series_color(si, s.get("name", ""))
                ax.plot(xs, ys, color=c, linewidth=2.4, label=lbl)
                ax.fill_between(xs, ys, xs, color=c,
                                alpha=0.15 if len(series_in) == 1 else 0.07)
            ax.set_xlim(0, 100)
            ax.set_ylim(0, 100)
            ax.set_xlabel("cumulative share of features (%)")
            ax.set_ylabel(f"cumulative share of {xlab or 'value'} (%)")
            self._legend(ax, theme)

        else:
            raise ValueError(f"Matplotlib engine does not support: {kind}")

    def _draw_overlays(self, ax, overlays, horizontal: bool = False) -> None:
        """Reference lines/bands (see core.overlays) as axhline / axhspan with
        an edge label, in the y-axis blended transform (x in axes fraction);
        vertical (axvline / axvspan) on horizontal bars."""
        if horizontal:
            trans = ax.get_xaxis_transform()
            for ov in overlays:
                color = ov.get("color")
                if ov.get("kind") == "line":
                    ax.axvline(ov["value"], color=color, zorder=4,
                               linewidth=ov.get("width", 1.5),
                               linestyle=(0, tuple(ov.get("dash") or (6, 4))))
                    ax.text(ov["value"], 0.995, ov.get("label", ""), transform=trans,
                            ha="left", va="top", color=color, fontsize=8, zorder=5)
                else:
                    ax.axvspan(ov["lo"], ov["hi"], color=color, zorder=0,
                               alpha=ov.get("opacity", 0.12))
                    ax.text(ov["hi"], 0.005, ov.get("label", ""), transform=trans,
                            ha="left", va="bottom", color=color, fontsize=8, zorder=5)
            return
        trans = ax.get_yaxis_transform()
        for ov in overlays:
            color = ov.get("color")
            if ov.get("kind") == "line":
                ax.axhline(ov["value"], color=color, zorder=4,
                           linewidth=ov.get("width", 1.5),
                           linestyle=(0, tuple(ov.get("dash") or (6, 4))))
                ax.text(0.995, ov["value"], ov.get("label", ""), transform=trans,
                        ha="right", va="bottom", color=color, fontsize=8, zorder=5)
            else:
                ax.axhspan(ov["lo"], ov["hi"], color=color, zorder=0,
                           alpha=ov.get("opacity", 0.12))
                ax.text(0.005, ov["hi"], ov.get("label", ""), transform=trans,
                        ha="left", va="bottom", color=color, fontsize=8, zorder=5)

    def _legend(self, ax, theme) -> None:
        leg = ax.legend(facecolor=theme["bg"], edgecolor=theme["grid"],
                        fontsize=9)
        for t in leg.get_texts():
            t.set_color(theme["text"])
