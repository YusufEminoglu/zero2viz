"""Versioned, read-only theme contract for sibling QGIS plugins.

The returned payload contains plain Python values only. Consumers never import
02viz internals and can retain a theme snapshot when 02viz is disabled later.
"""
from __future__ import annotations

from copy import deepcopy

from ..engines.base import DEFAULT_THEME, THEMES


API_ID = "zero2viz.print_layout_themes"
API_VERSION = 1

_TYPOGRAPHY = {
    "Studio Light": ("Segoe UI", 9.0, 5.6, 0.65),
    "Ink Dark": ("Segoe UI", 9.5, 5.7, 0.72),
    "Soft Pastel": ("Arial", 9.0, 5.6, 0.58),
    "Bold Print": ("Arial", 10.0, 5.8, 0.82),
}


def theme_catalog() -> dict:
    """Return an isolated, schema-versioned catalog for external consumers."""
    themes = []
    for name, source in THEMES.items():
        font, title_size, label_size, line_width = _TYPOGRAPHY[name]
        themes.append({
            "id": name.lower().replace(" ", "_"),
            "label": name,
            "palette": list(source["palette"]),
            "background": source["bg"],
            "text": source["text"],
            "grid": source["grid"],
            "font_family": font,
            "title_size_pt": title_size,
            "label_size_pt": label_size,
            "line_width_mm": line_width,
        })
    return deepcopy({
        "api": API_ID,
        "api_version": API_VERSION,
        "provider": "02viz",
        "default_theme": DEFAULT_THEME.lower().replace(" ", "_"),
        "themes": themes,
    })
