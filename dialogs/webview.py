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


def attach_title_listener(kind: str, view, callback) -> bool:
    """Wire the chart→map selection transport: forward the page's
    ``titleChanged`` notifications to ``callback`` (one ``str`` argument).

    ``titleChanged`` exists with the same signature on both QWebView and
    QWebEngineView, so this is the single code path for every QGIS build.
    (Do NOT switch back to addToJavaScriptWindowObject — it crashes the
    QtWebKit fork with an access violation during page commit.)
    Must be called once, before the first load. Returns True if wired."""
    if view is None:
        return False
    try:
        view.titleChanged.connect(callback)
        return True
    except Exception as exc:
        FALLBACK_LOG.append(f"title[{kind}]: {exc}")
        return False


def run_js(kind: str, view, code: str) -> bool:
    """Run JS in the page (QGIS → chart direction, e.g. cross-filter
    highlight). Safe on both stacks — unlike exposing Python objects to
    the page, evaluating a string does not touch the WebKit fork's
    broken object-injection path. Returns True if dispatched."""
    if view is None:
        return False
    try:
        if kind == "webkit":
            view.page().mainFrame().evaluateJavaScript(code)
            return True
        if kind == "webengine":
            view.page().runJavaScript(code)
            return True
    except Exception as exc:
        FALLBACK_LOG.append(f"runjs[{kind}]: {exc}")
    return False


def show_html_file(kind: str, view, path: str) -> bool:
    """Display the HTML file; returns True if shown embedded."""
    if view is not None:
        from qgis.PyQt.QtCore import QUrl

        view.load(QUrl.fromLocalFile(path))
        return True
    import webbrowser

    webbrowser.open("file:///" + path.replace("\\", "/"))
    return False
