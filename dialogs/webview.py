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


def attach_bridge(kind: str, view, bridge) -> bool:
    """Expose the SelectionBridge to the page as ``o2vizBridge``.
    Must be called once, before the first load. Returns True if wired."""
    if view is None:
        return False
    try:
        if kind == "webkit":
            frame = view.page().mainFrame()

            def _inject():
                frame.addToJavaScriptWindowObject("o2vizBridge", bridge)

            frame.javaScriptWindowObjectCleared.connect(_inject)
            return True
        if kind == "webengine":
            from qgis.PyQt.QtWebChannel import QWebChannel

            channel = QWebChannel(view.page())
            channel.registerObject("o2vizBridge", bridge)
            view.page().setWebChannel(channel)
            view._o2viz_channel = channel  # keep alive
            return True
    except Exception as exc:
        FALLBACK_LOG.append(f"bridge[{kind}]: {exc}")
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
