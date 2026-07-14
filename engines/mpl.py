# -*- coding: utf-8 -*-
"""Matplotlib / seaborn engine — optional, publication-grade *static* charts.

Unlike the vendored JS engines, this renders the spec to a static figure with
matplotlib (seaborn styling when present) and embeds it as a base64 PNG in the
same HTML shell, so the dock viewer and one-file export work unchanged. The
trade-off is no chart→map interactivity — this is the print/publication path.

matplotlib lives in the QGIS Python on most installs; when it doesn't, the
engine reports unavailable and the dock offers to install it (see
``core.requirements``). The import is lazy so it never slows QGIS startup.
"""
from __future__ import annotations

import base64
import io

from ..core import requirements
from .base import FONT_FAMILY, ChartEngine, theme_of

# the subset matplotlib/seaborn draws cleanly from the existing spec; the dock
# greys out the rest for this engine (treemap/sunburst/radar/pareto/error*)
_SUPPORTED = frozenset({
    "bar", "line", "area", "scatter", "bubble", "histogram",
    "pie", "box", "heatmap", "density", "violin",
})

# chart types that carry reference lines/bands on their value axis (core.overlays)
_OVERLAY_OK = frozenset(("bar", "line", "area", "scatter", "bubble"))

_IMG_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  html, body {{ margin: 0; width: 100%; height: 100%; background: {bg};
               display: flex; align-items: center; justify-content: center; }}
  img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
</style></head>
<body>
<img alt="{title}" src="data:image/png;base64,{b64}"/>
<script>
  // static image — keep the dock's bridge calls inert and mark ready
  window.__o2vizSelect = function () {{}};
  window.__o2vizHighlight = function () {{}};
  window.__chartReady = true;
</script>
</body></html>
"""


class MatplotlibEngine(ChartEngine):
    id = "matplotlib"
    label = "Matplotlib / seaborn"
    supports = _SUPPORTED

    @classmethod
    def available(cls) -> bool:
        return requirements.library_available("matplotlib")

    def build_html(self, spec: dict) -> str:
        if not self.available():
            raise RuntimeError(
                "matplotlib is not installed in this QGIS Python")
        b64 = self._render_png(spec)
        theme = theme_of(spec)
        return _IMG_HTML.format(title=spec.get("title", "02viz chart") or "chart",
                                bg=theme.get("bg", "#ffffff"), b64=b64)

    # ───────────────────── figure builder ─────────────────────

    def _render_png(self, spec: dict) -> str:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        try:
            import seaborn as sns
            sns.set_theme(style="whitegrid")
        except Exception:
            sns = None

        kind = spec["type"]
        data = spec.get("data", {})
        theme = theme_of(spec)
        palette = theme["palette"]
        bg, text, grid = theme["bg"], theme["text"], theme["grid"]

        plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans", "sans-serif"]
        fig, ax = plt.subplots(figsize=(8.2, 5.0), dpi=150)
        fig.patch.set_facecolor(bg)
        ax.set_facecolor(bg)

        def col(i):
            return palette[i % len(palette)]

        try:
            self._draw(kind, ax, data, spec, np, col, palette, theme)
            self._style_axes(ax, theme, kind)
            if spec.get("overlays") and kind in _OVERLAY_OK:
                self._draw_overlays(ax, spec["overlays"])
            if spec.get("title"):
                ax.set_title(spec["title"], color=text, fontsize=15,
                             fontweight="bold")
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                        facecolor=fig.get_facecolor())
            return base64.b64encode(buf.getvalue()).decode("ascii")
        finally:
            plt.close(fig)

    def _style_axes(self, ax, theme, kind) -> None:
        text, grid, bg = theme["text"], theme["grid"], theme["bg"]
        ax.tick_params(colors=text, labelsize=9)
        ax.xaxis.label.set_color(text)
        ax.yaxis.label.set_color(text)
        for spine in ax.spines.values():
            spine.set_color(grid)
        if kind not in ("pie", "heatmap"):
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.grid(True, axis="y", color=grid, linestyle="--", alpha=0.6)
            ax.set_axisbelow(True)

    def _draw(self, kind, ax, data, spec, np, col, palette, theme) -> None:
        text = theme["text"]
        xlab, ylab = spec.get("x_label", ""), spec.get("y_label", "")

        def cat_series():
            return (data.get("categories", []),
                    data.get("series") or [{"name": ylab or "value",
                                            "values": data.get("values", [])}])

        if kind in ("bar", "histogram"):
            cats, series = cat_series()
            xi = np.arange(len(cats))
            if kind == "histogram" or len(series) == 1:
                ax.bar(xi, series[0]["values"], color=col(0), width=0.86)
            elif spec.get("stacked"):
                bottom = np.zeros(len(cats))
                for si, s in enumerate(series):
                    v = np.array(s["values"], dtype=float)
                    ax.bar(xi, v, bottom=bottom, color=col(si), label=s["name"])
                    bottom += v
            else:
                w = 0.8 / max(1, len(series))
                for si, s in enumerate(series):
                    ax.bar(xi - 0.4 + w * (si + 0.5), s["values"], w,
                           color=col(si), label=s["name"])
            ax.set_xticks(xi)
            ax.set_xticklabels(cats, rotation=30, ha="right")
            ax.set_xlabel(xlab)
            ax.set_ylabel("count" if kind == "histogram" else ylab)
            if len(series) > 1:
                self._legend(ax, theme)

        elif kind in ("line", "area"):
            cats, series = cat_series()
            xi = np.arange(len(cats))
            for si, s in enumerate(series):
                ax.plot(xi, s["values"], marker="o", color=col(si),
                        label=s["name"], linewidth=2.4)
                if kind == "area":
                    ax.fill_between(xi, s["values"], color=col(si), alpha=0.3)
            ax.set_xticks(xi)
            ax.set_xticklabels(cats, rotation=30, ha="right")
            ax.set_xlabel(xlab)
            ax.set_ylabel(ylab)
            if len(series) > 1:
                self._legend(ax, theme)

        elif kind in ("scatter", "bubble"):
            for si, s in enumerate(data.get("series", [])):
                pts = s.get("points", [])
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                sizes = [(p[2] ** 2 if len(p) > 2 and p[2] else 42) for p in pts]
                ax.scatter(xs, ys, s=sizes, color=col(si), alpha=0.75,
                           edgecolors="none", label=s.get("name", ""))
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
                   colors=[col(i) for i in range(len(cats))],
                   textprops={"color": text}, wedgeprops={"width": 0.55})
            ax.axis("equal")

        elif kind == "box":
            groups = data.get("groups", [])
            stats = data.get("stats", [])
            bxp = [{"med": s[2], "q1": s[1], "q3": s[3],
                    "whislo": s[0], "whishi": s[4], "label": g}
                   for g, s in zip(groups, stats)]
            box = ax.bxp(bxp, showfliers=False, patch_artist=True)
            for i, patch in enumerate(box["boxes"]):
                patch.set_facecolor(col(i))
                patch.set_alpha(0.75)
            ax.set_ylabel(ylab)
            ax.tick_params(axis="x", rotation=30)

        elif kind == "heatmap":
            x_cats = data.get("x_cats", [])
            y_cats = data.get("y_cats", [])
            Z = np.full((len(y_cats), len(x_cats)), np.nan)
            for xi_, yi_, v in data.get("cells", []):
                Z[yi_][xi_] = v
            cmap = "RdBu_r" if data.get("diverging") else "viridis"
            im = ax.imshow(Z, cmap=cmap, aspect="auto")
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
                ax.plot(xs, ys, color=col(si), label=s.get("name", ""),
                        linewidth=2)
                ax.fill_between(xs, ys, color=col(si), alpha=0.3)
            ax.set_xlabel(xlab)
            ax.set_ylabel("density")
            if len(data.get("series", [])) > 1:
                self._legend(ax, theme)

        elif kind == "violin":
            groups = data.get("groups", [])
            for i, poly in enumerate(data.get("polygons", [])):
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                ax.fill(xs, ys, color=col(i), alpha=0.6)
            meds = data.get("medians", [])
            ax.scatter(range(len(meds)), meds, color=theme["text"], zorder=3, s=24)
            ax.set_xticks(range(len(groups)))
            ax.set_xticklabels(groups, rotation=30, ha="right")
            ax.set_ylabel(ylab)

        else:
            raise ValueError(f"Matplotlib engine does not support: {kind}")

    def _draw_overlays(self, ax, overlays) -> None:
        """Reference lines/bands (see core.overlays) as axhline / axhspan with
        an edge label, in the y-axis blended transform (x in axes fraction)."""
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
