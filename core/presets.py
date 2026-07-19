"""Validation and JSON storage helpers for reusable chart presets.

The dock owns the widgets and QSettings integration; this module keeps the
stored format small, versioned and safe to read after a partial settings edit.
It deliberately has no QGIS imports so the format is independently testable.
"""
from __future__ import annotations

import json
import re


SCHEMA_VERSION = 1
MAX_PRESETS = 50
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_TEXT_KEYS = {
    "engine", "type", "theme", "palette", "title", "aggregation",
    "sort", "target", "custom_spec",
}
_INT_KEYS = {"speed", "bins", "top_n"}
_BOOL_KEYS = {
    "selected_only", "stacked", "trend", "link", "mean", "median",
    "sigma", "iqr", "custom_spec_enabled",
}
_FIELD_KEYS = {"x", "y", "group", "value", "animate"}


def sanitize_preset(value: object) -> dict | None:
    """Return a clean preset dictionary, or None for unusable input."""
    if not isinstance(value, dict):
        return None
    clean: dict = {"schema": SCHEMA_VERSION}
    for key in _TEXT_KEYS:
        item = value.get(key)
        if isinstance(item, str):
            clean[key] = item[:200000 if key == "custom_spec" else 500]
    for key in _INT_KEYS:
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool):
            clean[key] = item
    for key in _BOOL_KEYS:
        item = value.get(key)
        if isinstance(item, bool):
            clean[key] = item
    fields = value.get("fields")
    if isinstance(fields, dict):
        clean["fields"] = {
            key: item[:500] for key, item in fields.items()
            if key in _FIELD_KEYS and isinstance(item, str)
        }
    colors = value.get("custom_palette")
    if isinstance(colors, list):
        clean["custom_palette"] = [
            color.lower() for color in colors[:16]
            if isinstance(color, str) and _COLOR.fullmatch(color)
        ]
    if not clean.get("engine") or not clean.get("type"):
        return None
    return clean


def decode_library(raw: object) -> dict[str, dict]:
    """Decode a QSettings value, dropping malformed names and presets."""
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict] = {}
    for name, preset in value.items():
        if len(result) >= MAX_PRESETS:
            break
        if not isinstance(name, str) or not name.strip():
            continue
        clean = sanitize_preset(preset)
        if clean is not None:
            result[name.strip()[:100]] = clean
    return result


def encode_library(library: dict[str, dict]) -> str:
    """Encode a deterministic, sanitized preset library for QSettings."""
    clean: dict[str, dict] = {}
    for name in sorted(library, key=str.casefold):
        if len(clean) >= MAX_PRESETS:
            break
        if not isinstance(name, str) or not name.strip():
            continue
        preset = sanitize_preset(library[name])
        if preset is not None:
            clean[name.strip()[:100]] = preset
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
