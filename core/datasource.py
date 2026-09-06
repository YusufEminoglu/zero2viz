# -*- coding: utf-8 -*-
"""Data binding: pull row-aligned columns out of any vector layer.

A "data source" is simply a QgsVectorLayer — spatial or not. External
tables (CSV, XLSX, ODS, GeoPackage tables…) are opened through OGR and
added to the project, so they show up in the same layer combo as map
layers and everything downstream stays uniform.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from qgis.core import QgsProject, QgsVectorLayer

MAX_ROWS = 100_000  # hard cap so a misclick on a huge layer never freezes QGIS


@dataclass(frozen=True)
class ExtractionInfo:
    """Provenance for one bounded layer-to-chart extraction."""

    loaded_rows: int
    available_rows: int
    truncated: bool
    selected_only: bool

    @property
    def status_note(self) -> str:
        if self.truncated:
            total = (f"{self.available_rows:,}" if self.available_rows >= 0
                     else "more than the safety limit")
            return f"first {self.loaded_rows:,} of {total} rows"
        scope = "selected" if self.selected_only else "available"
        return f"all {self.loaded_rows:,} {scope} rows"


def columns(layer, field_names: list[str], selected_only: bool = False) -> dict[str, list]:
    """Row-aligned column extraction. Missing/NULL values become None."""
    cols, _ = columns_with_ids(layer, field_names, selected_only)
    return cols


def columns_with_ids(layer, field_names: list[str],
                     selected_only: bool = False) -> tuple[dict[str, list], list]:
    """Like :func:`columns` but also returns the feature id per row, so
    charts can select their features back on the canvas."""
    cols, fids, _info = columns_with_ids_info(
        layer, field_names, selected_only)
    return cols, fids


def columns_with_ids_info(
        layer,
        field_names: list[str],
        selected_only: bool = False,
        max_rows: int = MAX_ROWS) -> tuple[dict[str, list], list, ExtractionInfo]:
    """Extract columns plus an explicit completeness/provenance record."""
    limit = max(1, int(max_rows))
    out: dict[str, list] = {name: [] for name in field_names}
    fids: list = []
    idx = {name: layer.fields().lookupField(name) for name in field_names}
    missing = [n for n, i in idx.items() if i < 0]
    if missing:
        raise ValueError(f"Field(s) not found: {', '.join(missing)}")

    available = (int(layer.selectedFeatureCount()) if selected_only
                 else int(layer.featureCount()))
    feats = layer.selectedFeatures() if selected_only else layer.getFeatures()
    saw_extra = False
    for feat in feats:
        if len(fids) >= limit:
            saw_extra = True
            break
        fids.append(feat.id())
        attrs = feat.attributes()
        for name in field_names:
            value = attrs[idx[name]]
            # QVariant NULL arrives as a falsy QVariant or None depending on API version
            if value is None or repr(value) == "NULL" or str(type(value).__name__) == "QVariant":
                out[name].append(None)
            else:
                out[name].append(value)
    truncated = saw_extra or (available >= 0 and available > len(fids))
    return out, fids, ExtractionInfo(
        loaded_rows=len(fids),
        available_rows=available,
        truncated=truncated,
        selected_only=selected_only,
    )


def load_table(path: str):
    """Open an external table (CSV/XLSX/ODS/…) via OGR and add it to the
    project so it appears in layer combos. Returns the layer or None."""
    name = os.path.splitext(os.path.basename(path))[0]
    layer = QgsVectorLayer(path, name, "ogr")
    if not layer.isValid():
        return None
    QgsProject.instance().addMapLayer(layer)
    return layer
