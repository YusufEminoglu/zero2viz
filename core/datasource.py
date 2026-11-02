# -*- coding: utf-8 -*-
"""Data binding: pull row-aligned columns out of any vector layer.

A "data source" is simply a QgsVectorLayer — spatial or not. External
tables are added to the project, so they show up in the same layer combo as
map layers and everything downstream stays uniform: CSV / TXT / TSV through
QGIS's delimited-text provider with column type detection (so numbers are
numbers, not text), XLSX / ODS / GeoPackage / DBF through OGR.

Date, datetime and time values leave this module as ISO 8601 text
("2024-02-01", "2024-02-01T08:00:00"), never as Qt objects, so charts label
and sort them as dates.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QUrl, QUrlQuery

from .stats import is_temporal, temporal_iso

MAX_ROWS = 100_000  # hard cap so a misclick on a huge layer never freezes QGIS
DELIMITED_EXTENSIONS = (".csv", ".tsv", ".txt")
_DECIMAL_COMMA_RE = re.compile(r"(?:^|;)\s*\"?-?\d+,\d+\"?\s*(?:;|$)")


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
            out[name].append(plain_value(attrs[idx[name]]))
    truncated = saw_extra or (available >= 0 and available > len(fids))
    return out, fids, ExtractionInfo(
        loaded_rows=len(fids),
        available_rows=available,
        truncated=truncated,
        selected_only=selected_only,
    )


def plain_value(value):
    """One attribute value as a plain Python value: NULL → None, dates /
    datetimes / times → ISO 8601 text, everything else unchanged."""
    if value is None:
        return None
    if type(value) in (str, int, float, bool):
        return value
    # QVariant NULL arrives as a falsy QVariant or None depending on API version
    if repr(value) == "NULL" or str(type(value).__name__) == "QVariant":
        return None
    if is_temporal(value):
        return temporal_iso(value)  # None for an invalid (null) date
    return value


def _sniff_delimiter(path: str) -> tuple[str, bool]:
    """(delimiter, decimal_comma) from the first lines of a text table."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            lines = [handle.readline() for _ in range(20)]
    except OSError:
        return ",", False
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return ",", False
    header = lines[0]
    if path.lower().endswith(".tsv"):
        delimiter = "\t"
    else:
        counts = {d: header.count(d) for d in (",", ";", "\t", "|")}
        delimiter = max(counts, key=lambda d: counts[d])
        if counts[delimiter] == 0:
            delimiter = ","
    decimal_comma = delimiter == ";" and any(
        _DECIMAL_COMMA_RE.search(ln.strip()) for ln in lines[1:])
    return delimiter, decimal_comma


def delimited_uri(path: str) -> str:
    """A delimited-text provider URI that detects column types (integer,
    decimal, date, boolean) instead of loading every column as text."""
    delimiter, decimal_comma = _sniff_delimiter(path)
    url = QUrl.fromLocalFile(os.path.abspath(path))
    query = QUrlQuery()
    query.addQueryItem("type", "csv")
    query.addQueryItem("delimiter", "\\t" if delimiter == "\t" else delimiter)
    query.addQueryItem("encoding", "UTF-8")
    query.addQueryItem("detectTypes", "yes")
    query.addQueryItem("geomType", "none")
    query.addQueryItem("subsetIndex", "no")
    query.addQueryItem("watchFile", "no")
    if decimal_comma:
        query.addQueryItem("decimalPoint", ",")
    url.setQuery(query)
    return bytes(url.toEncoded()).decode("ascii")


def open_table(path: str):
    """Open an external table without adding it to the project. CSV / TSV /
    TXT use the delimited-text provider with type detection (falling back to
    OGR if it cannot read the file); other formats use OGR. → layer or None."""
    name = os.path.splitext(os.path.basename(path))[0]
    layer = None
    if path.lower().endswith(DELIMITED_EXTENSIONS):
        layer = QgsVectorLayer(delimited_uri(path), name, "delimitedtext")
        if not layer.isValid():
            layer = None
    if layer is None:
        layer = QgsVectorLayer(path, name, "ogr")
    return layer if layer.isValid() else None


def load_table(path: str):
    """Open an external table (see :func:`open_table`) and add it to the
    project so it appears in layer combos. Returns the layer or None."""
    layer = open_table(path)
    if layer is None:
        return None
    QgsProject.instance().addMapLayer(layer)
    return layer
