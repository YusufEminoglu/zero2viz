# -*- coding: utf-8 -*-
"""QGIS expression builders — pure strings, no ``qgis`` import.

Two on-canvas surfaces compose QGIS expressions instead of reading a raw
field, and both want their string assembly to unit-test without a running
QGIS:

* **Labels** — round / thousands grouping / prefix-suffix / case / word-wrap
  and a multi-line join of several fields (the ``\\n`` the user asked for),
  with a free-form advanced expression that overrides everything.
* **Map diagrams** — normalise differently-scaled fields (min–max, z-score,
  log) so a pie slice or bar height is *comparable* between fields instead of
  being dominated by whichever field happens to carry the bigger numbers.

Every function returns a valid QGIS expression string; the dock feeds these
to ``QgsPalLayerSettings`` (``isExpression = True``) or to a diagram's
``categoryAttributes``.
"""
from __future__ import annotations


def _num(x) -> str:
    """A float as a literal a QGIS expression parses back to the same value."""
    return "%.12g" % float(x)


def quote_field(name: str) -> str:
    """Double-quote a field name for an expression, escaping embedded quotes."""
    return '"' + str(name).replace('"', '""') + '"'


def quote_str(text: str) -> str:
    """Single-quote a string literal for an expression, escaping quotes."""
    return "'" + str(text).replace("'", "''") + "'"


# ───────────────────────────── labels ─────────────────────────────

LABEL_CASES = ("none", "upper", "lower", "title")
LABEL_CASE_LABELS = {
    "none": "As is",
    "upper": "UPPERCASE",
    "lower": "lowercase",
    "title": "Title Case",
}


def _format_field(name: str, decimals: int, thousands: bool) -> str:
    """One field reference, optionally rounded / thousands-grouped."""
    f = quote_field(name)
    if decimals is not None and decimals >= 0:
        # format_number already groups thousands and fixes the decimal count;
        # round() keeps a bare number when no grouping is wanted
        return "format_number(%s, %d)" % (f, decimals) if thousands \
            else "round(%s, %d)" % (f, decimals)
    if thousands:
        return "format_number(%s, 0)" % f
    return f


def label_expression(fields, *, decimals: int = -1, thousands: bool = False,
                     prefix: str = "", suffix: str = "", case: str = "none",
                     wrap: int = 0, multiline: bool = True,
                     numeric_fields=None, custom: str = "") -> str:
    """Assemble a QGIS label expression from the Labels-tab controls.

    ``custom`` (a full expression typed by the user) wins outright. Otherwise
    one or more ``fields`` are formatted (``decimals`` ≥ 0 rounds; ``thousands``
    groups), joined on a newline (``multiline``) or a space, wrapped in
    ``prefix``/``suffix``, re-cased and word-wrapped at ``wrap`` characters.

    Number formatting is applied only to fields in ``numeric_fields`` (so a
    text field on a second line is never wrapped in ``round()``); ``None`` —
    the default — formats every field.
    """
    custom = (custom or "").strip()
    if custom:
        return custom

    names = [n for n in (fields or []) if n]
    if not names:
        return "''"

    # char(10) is an unambiguous newline across QGIS versions (no reliance on
    # backslash-escape handling inside a quoted literal). Build one flat
    # concat(prefix, f1, sep, f2, …, suffix) rather than nesting.
    sep = "char(10)" if multiline else "' '"
    operands: list[str] = []
    if prefix:
        operands.append(quote_str(prefix))
    for i, name in enumerate(names):
        if i:
            operands.append(sep)
        is_num = numeric_fields is None or name in numeric_fields
        operands.append(_format_field(name, decimals if is_num else -1,
                                      thousands if is_num else False))
    if suffix:
        operands.append(quote_str(suffix))
    expr = operands[0] if len(operands) == 1 else "concat(%s)" % ", ".join(operands)

    if case == "upper":
        expr = "upper(%s)" % expr
    elif case == "lower":
        expr = "lower(%s)" % expr
    elif case == "title":
        expr = "title(%s)" % expr

    if wrap and wrap > 0:
        expr = "wordwrap(%s, %d)" % (expr, int(wrap))
    return expr


# ─────────────────────────── map diagrams ───────────────────────────

NORMALIZE_MODES = ("none", "minmax", "zscore", "log")
NORMALIZE_LABELS = {
    "none": "None — raw values",
    "minmax": "Min–max (0–1)",
    "zscore": "Z-score (standardise)",
    "log": "Log (compress range)",
}
# modes that can go negative don't suit area/angle-encoded diagrams (pie,
# stacked bar): a slice can't have a negative angle. The dock uses this to warn.
NONNEGATIVE_MODES = frozenset(("none", "minmax", "log"))


def normalize_expression(field: str, mode: str, st: dict) -> str:
    """Expression for one diagram category, normalised per ``mode``.

    ``st`` is the field's ``{"min","max","mean","std"}`` (see
    :func:`core.stats.field_numeric_stats`). Degenerate stats (flat field,
    zero spread) fall back to the raw field so a diagram never divides by zero
    or takes the log of a non-positive number.
    """
    f = quote_field(field)
    if not st or mode == "none":
        return f
    if mode == "minmax":
        rng = st["max"] - st["min"]
        if rng <= 0:
            return f
        return "((%s) - (%s)) / (%s)" % (f, _num(st["min"]), _num(rng))
    if mode == "zscore":
        if st["std"] <= 0:
            return f
        return "((%s) - (%s)) / (%s)" % (f, _num(st["mean"]), _num(st["std"]))
    if mode == "log":
        # shift so the smallest value maps to ln(1) = 0; keeps it defined for
        # zeros and negatives while staying monotonic
        shift = 1.0 - st["min"]
        return "ln((%s) + (%s))" % (f, _num(shift))
    return f
