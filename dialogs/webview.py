# -*- coding: utf-8 -*-
"""Embedded chart viewer with graceful degradation.

QGIS builds differ wildly in what web widget they ship:
QtWebEngine (Chromium) → QtWebKit (legacy QWebView) → nothing.
We try in that order and finally fall back to the system browser.
"""
from __future__ import annotations

# why each backend was rejected, for support/diagnostics
FALLBACK_LOG: list[str] = []


def create_chart_view(parent=None):
    """Returns (kind, widget). kind ∈ {'webengine', 'webkit', 'browser'};
    widget is None for the 'browser' fallback."""
    try:
        from qgis.PyQt.QtWebEngineWidgets import QWebEngineView

        return "webengine", QWebEngineView(parent)
    except Exception as exc:
        FALLBACK_LOG.append(f"webengine: {exc}")
    try:
        from qgis.PyQt.QtWebKitWidgets import QWebView

        return "webkit", QWebView(parent)
    except Exception as exc:
        FALLBACK_LOG.append(f"webkit: {exc}")
        return "browser", None


def show_html_file(kind: str, view, path: str) -> bool:
    """Display the HTML file; returns True if shown embedded."""
    if view is not None:
        from qgis.PyQt.QtCore import QUrl

        view.load(QUrl.fromLocalFile(path))
        return True
    import webbrowser

    webbrowser.open("file:///" + path.replace("\\", "/"))
    return False
