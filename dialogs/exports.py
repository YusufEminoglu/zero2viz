# -*- coding: utf-8 -*-
"""Honest chart exports: the page draws, Python writes the file.

Every engine page defines ``window.o2vizExport(format, width, height)``, a
Promise of an SVG string for ``"svg"`` or a PNG data URL for ``"png"`` at the
given CSS pixel size (docs/DEVELOPMENT_SET_v0.20.md §3). This module calls it
through either web stack and turns the answer into files:

* SVG: the engine's own vector export, written as text;
* PNG: the engine's raster, drawn again at the size the user picked;
* PDF: drawn in Python from that SVG with ``QSvgRenderer`` onto a
  ``QPdfWriter``, so paths and text stay vector. Never a picture of the widget.

It also saves the files a page offers through its own toolbar (the ECharts and
Plotly download buttons), which arrive as a download request on the web view.

The page call works on both stacks with one polling bridge: the start script
parks the settled Promise in ``window.__o2vizExportJobs[token]`` and Python
polls that slot (WebEngine ``runJavaScript`` callbacks, WebKit
``evaluateJavaScript`` return values) until it is filled or the call times out.
"""
from __future__ import annotations

import base64
import contextlib
import itertools
import json
import os
import time
import urllib.parse

from qgis.PyQt.QtCore import QTimer

from ..core.export_utils import atomic_output
from .webview import eval_js

EXPORT_TIMEOUT_MS = 30000
_POLL_MS = 60
_TOKENS = itertools.count(1)
_ACTIVE: set = set()  # keeps running jobs alive until they settle

MISSING_EXPORT = ("This chart page has no vector/image export. "
                  "Use Export HTML, or render the chart again.")
EXPLORE_EXPORT = ("The Explore dashboard is saved as HTML only. Render one "
                  "chart to export it as SVG, PNG or PDF.")

PROBE_JS = ("(function () { return (typeof window.o2vizExport === 'function')"
            " ? 'ready' : 'missing'; })();")

_START_JS = """(function (fmt, w, h, token) {
  var jobs = window.__o2vizExportJobs || (window.__o2vizExportJobs = {});
  function settle(ok, value, error) {
    jobs[token] = {done: true, ok: ok, value: ok ? String(value) : "", error: ok ? "" : error};
  }
  if (typeof window.o2vizExport !== "function") { settle(false, "", "missing"); return "missing"; }
  jobs[token] = {done: false};
  try {
    var r = window.o2vizExport(fmt, w, h);
    var take = function (v) {
      settle(typeof v === "string" && v.length > 0, v, "the chart page returned nothing");
    };
    var fail = function (e) { settle(false, "", String((e && e.message) || e)); };
    if (r && typeof r.then === "function") { r.then(take, fail); } else { take(r); }
  } catch (e) {
    settle(false, "", String((e && e.message) || e));
  }
  return "started";
})(%s, %d, %d, %s);"""

_POLL_JS = """(function (token) {
  var jobs = window.__o2vizExportJobs || {};
  var job = jobs[token];
  if (!job) { return "lost"; }
  if (!job.done) { return "pending"; }
  delete jobs[token];
  return JSON.stringify(job);
})(%s);"""


class _ExportJob:
    """One ``o2vizExport`` call; ``done(ok, payload_or_message)`` fires once."""

    def __init__(self, kind, view, fmt, width, height, done, timeout_ms):
        self.kind, self.view, self.done = kind, view, done
        self.token = json.dumps(f"t{next(_TOKENS)}")
        self.start_code = _START_JS % (json.dumps(fmt), int(width), int(height),
                                       self.token)
        self.timeout_ms = timeout_ms
        self.deadline = time.monotonic() + timeout_ms / 1000.0
        self.settled = False

    def start(self) -> None:
        _ACTIVE.add(self)
        QTimer.singleShot(self.timeout_ms + 500, self._watchdog)
        if not eval_js(self.kind, self.view, self.start_code, self._started):
            self._finish(False, "The chart view cannot run scripts.")

    def _started(self, value) -> None:
        if value == "missing":
            self._finish(False, MISSING_EXPORT)
        elif value != "started":
            self._finish(False, "The chart page did not start the export.")
        else:
            self._poll()

    def _poll(self) -> None:
        if self.settled:
            return
        if not eval_js(self.kind, self.view, _POLL_JS % self.token, self._polled):
            self._finish(False, "The chart view stopped answering.")

    def _polled(self, value) -> None:
        if self.settled:
            return
        if value == "pending":
            if time.monotonic() > self.deadline:
                self._finish(False, "The chart page took too long to draw the export.")
            else:
                QTimer.singleShot(_POLL_MS, self._poll)
            return
        if not isinstance(value, str) or value == "lost":
            self._finish(False, "The chart page reloaded during the export.")
            return
        try:
            job = json.loads(value)
        except ValueError:
            self._finish(False, "The chart page answered with something unreadable.")
            return
        if job.get("ok") and isinstance(job.get("value"), str):
            self._finish(True, job["value"])
        else:
            error = str(job.get("error") or "the chart page could not draw the export")
            self._finish(False, MISSING_EXPORT if error == "missing" else error)

    def _watchdog(self) -> None:
        self._finish(False, "The chart page took too long to draw the export.")

    def _finish(self, ok: bool, payload: str) -> None:
        if self.settled:
            return
        self.settled = True
        _ACTIVE.discard(self)
        self.done(ok, payload)


def call_page_export(kind, view, fmt, width, height, done,
                     timeout_ms: int = EXPORT_TIMEOUT_MS) -> None:
    """Ask the page for ``fmt`` ("svg" | "png") at ``width`` × ``height`` CSS
    pixels; ``done(ok, payload)`` receives the SVG text / PNG data URL, or a
    plain-English reason when ``ok`` is False."""
    _ExportJob(kind, view, fmt, width, height, done, timeout_ms).start()


def run_page_export(kind, view, fmt, width, height,
                    timeout_ms: int = EXPORT_TIMEOUT_MS) -> str:
    """Blocking form of :func:`call_page_export` for the Save dialogs and the
    tests: spins a local event loop until the page answers or the call times
    out. Raises ``ValueError`` with the reason on failure."""
    from qgis.PyQt.QtCore import QEventLoop

    result: dict = {}
    loop = QEventLoop()

    def done(ok, payload):
        result["ok"] = ok
        result["payload"] = payload
        loop.quit()

    call_page_export(kind, view, fmt, width, height, done, timeout_ms)
    if "ok" not in result:
        loop.exec()
    if not result.get("ok"):
        raise ValueError(result.get("payload") or "The chart page did not answer.")
    return result["payload"]


# ───────────────────────── payload checks ─────────────────────────

def data_url_payload(url: str) -> tuple[str, bytes] | None:
    """``(mime, bytes)`` of a ``data:`` URL, or None for anything else."""
    if not isinstance(url, str) or not url.startswith("data:"):
        return None
    head, sep, body = url[5:].partition(",")
    if not sep:
        return None
    mime = head.split(";")[0].strip().lower() or "text/plain"
    try:
        if ";base64" in head.lower():
            data = base64.b64decode(body)
        else:
            data = urllib.parse.unquote_to_bytes(body)
    except (ValueError, TypeError):
        return None
    return mime, data


def svg_text(payload: str) -> str:
    """The SVG document in ``payload`` (raw markup or an SVG data URL)."""
    text = payload
    decoded = data_url_payload(payload)
    if decoded is not None:
        mime, data = decoded
        if mime != "image/svg+xml":
            raise ValueError("The chart page did not return an SVG drawing.")
        text = data.decode("utf-8", errors="replace")
    if not isinstance(text, str):
        raise ValueError("The chart page did not return an SVG drawing.")
    text = text.lstrip("﻿ \t\r\n")
    if "<svg" not in text[:4000].lower():
        raise ValueError("The chart page did not return an SVG drawing.")
    return text


def png_bytes(payload: str) -> bytes:
    """The PNG file inside a PNG data URL, checked by its signature."""
    decoded = data_url_payload(payload)
    if decoded is None or decoded[0] != "image/png":
        raise ValueError("The chart page did not return a PNG image.")
    data = decoded[1]
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The chart page returned a damaged PNG image.")
    return data


# ───────────────────────── file writers ─────────────────────────

def write_bytes(path: str, data: bytes) -> int:
    with atomic_output(path) as temporary_path:
        with open(temporary_path, "wb") as handle:
            handle.write(data)
    return os.path.getsize(os.path.abspath(path))


def write_svg(path: str, svg: str) -> int:
    return write_bytes(path, svg.encode("utf-8"))


def svg_to_pdf(svg: str, path: str) -> int:
    """Draw ``svg`` onto a one-page PDF the size of the drawing (vector).

    1 CSS pixel = 0.75 pt, the same mapping a browser uses when printing."""
    from qgis.PyQt.QtCore import QByteArray, QMarginsF, QRectF, QSizeF
    from qgis.PyQt.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
    from qgis.PyQt.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise ValueError("Qt could not read the chart's SVG drawing.")
    box = renderer.viewBoxF()
    size = renderer.defaultSize()
    width = float(size.width()) if size.width() > 0 else box.width()
    height = float(size.height()) if size.height() > 0 else box.height()
    if width <= 0 or height <= 0:
        raise ValueError("The chart's SVG drawing has no size.")
    with atomic_output(path) as temporary_path:
        writer = QPdfWriter(temporary_path)
        writer.setResolution(96)
        writer.setCreator("02viz")
        writer.setTitle("02viz chart")
        page = QPageSize(QSizeF(width * 0.75, height * 0.75), QPageSize.Unit.Point,
                         "02viz chart", QPageSize.SizeMatchPolicy.ExactMatch)
        writer.setPageLayout(QPageLayout(page, QPageLayout.Orientation.Portrait,
                                         QMarginsF(0, 0, 0, 0)))
        painter = QPainter()
        if not painter.begin(writer):
            raise ValueError("Qt could not start the PDF writer.")
        try:
            target = painter.viewport()
            renderer.render(painter, QRectF(0, 0, target.width(), target.height()))
        finally:
            painter.end()
        # QPdfWriter keeps the file open for its lifetime; release it before
        # atomic_output renames the staging file (required on Windows).
        del painter
        del writer
    return os.path.getsize(os.path.abspath(path))


# ───────────────────────── PNG size dialog ─────────────────────────

def ask_png_size(parent, width: int, height: int):
    """Ask for the PNG size in pixels; ``(width, height)`` or None if cancelled."""
    from qgis.PyQt.QtWidgets import (
        QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox,
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle("PNG size")
    form = QFormLayout(dialog)
    note = QLabel("The chart is drawn again at this size, so text and lines "
                  "stay sharp.")
    note.setWordWrap(True)
    form.addRow(note)
    boxes = []
    for label, value in (("Width", width), ("Height", height)):
        box = QSpinBox()
        box.setRange(200, 8000)
        box.setSingleStep(50)
        box.setSuffix(" px")
        box.setValue(int(min(8000, max(200, value))))
        form.addRow(label, box)
        boxes.append(box)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if not dialog.exec():
        return None
    return boxes[0].value(), boxes[1].value()


# ───────────────────────── page downloads ─────────────────────────

class EngineDownload:
    """A QtWebEngine download item (Qt5 QWebEngineDownloadItem or Qt6
    QWebEngineDownloadRequest) behind one small interface."""

    def __init__(self, item):
        self.item = item

    def suggested_name(self) -> str:
        for attr in ("suggestedFileName", "downloadFileName"):
            getter = getattr(self.item, attr, None)
            if getter is not None:
                name = getter()
                if name:
                    return os.path.basename(str(name))
        getter = getattr(self.item, "path", None)
        if getter is not None and getter():
            return os.path.basename(str(getter()))
        return "02viz_chart.png"

    def save_to(self, path: str) -> int:
        folder, name = os.path.split(os.path.abspath(path))
        if hasattr(self.item, "setDownloadDirectory"):
            self.item.setDownloadDirectory(folder)
            self.item.setDownloadFileName(name)
        else:
            self.item.setPath(path)
        self.item.accept()
        return 0  # the engine writes the file itself, asynchronously

    def when_done(self, report) -> bool:
        """Call ``report(ok, detail)`` once the engine has finished writing the
        file (Qt 5 ``finished``, Qt 6 ``isFinishedChanged``). False when the
        item has no such signal, so the caller cannot wait for it."""
        item = self.item
        signal = getattr(item, "isFinishedChanged", None) or getattr(item, "finished", None)
        if signal is None or not hasattr(signal, "connect"):
            return False

        def settled(*_args) -> None:
            finished = getattr(item, "isFinished", None)
            if callable(finished) and not finished():
                return
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(settled)
            report(*self._outcome())

        signal.connect(settled)
        return True

    def _outcome(self) -> tuple[bool, str]:
        state = getattr(self.item, "state", None)
        owner = type(self.item)
        completed = getattr(getattr(owner, "DownloadState", owner), "DownloadCompleted", None)
        if not callable(state) or completed is None:
            return True, ""
        if state() == completed:
            return True, ""
        reason = getattr(self.item, "interruptReasonString", None)
        detail = str(reason() or "") if callable(reason) else ""
        return False, detail or "the download did not finish"

    def cancel(self) -> None:
        self.item.cancel()


class KitDownload:
    """A QtWebKit download request; only self-contained ``data:`` URLs (what
    the chart toolbars produce) can be saved without the network."""

    _EXT = {"image/png": ".png", "image/svg+xml": ".svg", "image/jpeg": ".jpg",
            "text/csv": ".csv", "application/json": ".json"}

    def __init__(self, request):
        self.url = request.url().toString()

    def suggested_name(self) -> str:
        decoded = data_url_payload(self.url)
        ext = self._EXT.get(decoded[0], ".bin") if decoded else ".png"
        return "02viz_chart" + ext

    def save_to(self, path: str) -> int:
        decoded = data_url_payload(self.url)
        if decoded is None:
            raise ValueError("The page offered a file this panel cannot save; "
                             "use the Export menu instead.")
        return write_bytes(path, decoded[1])

    def cancel(self) -> None:
        return None


def attach_downloads(kind: str, view, handler):
    """Route the page's own downloads (toolbar buttons) to ``handler(download)``.

    Returns a function that detaches the handler again (call it on unload).
    WebEngine downloads arrive on the shared profile, so only items that come
    from *this* view's page are taken; everything else is left alone."""
    if view is None:
        return lambda: None
    if kind == "webengine":
        page = view.page()
        profile = page.profile()

        def on_engine(item):
            owner = getattr(item, "page", None)
            if owner is not None and owner() is not None and owner() != page:
                return
            handler(EngineDownload(item))

        profile.downloadRequested.connect(on_engine)
        return lambda: profile.downloadRequested.disconnect(on_engine)
    if kind == "webkit":
        page = view.page()

        def on_kit(request):
            handler(KitDownload(request))

        page.downloadRequested.connect(on_kit)
        return lambda: page.downloadRequested.disconnect(on_kit)
    return lambda: None
