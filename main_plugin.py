# -*- coding: utf-8 -*-
"""02viz - Geospatial Visualization Studio: main plugin class.

Toolbar + menu + togglable studio dock. The dock hosts the chart studio
(engine selection, data binding, chart gallery); rendering engines are
loaded lazily so QGIS startup stays instant.
"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QMenu, QMessageBox, QToolBar

try:  # Qt5: QtWidgets / Qt6: QtGui
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # pragma: no cover - QGIS 4 / Qt6
    from qgis.PyQt.QtGui import QAction

PLUGIN_NAME = "02viz"
PLUGIN_TITLE = "02viz - Geospatial Visualization Studio"


class O2VizPlugin:
    MENU_NAME = "&02viz"
    TOOLBAR_NAME = "02viz Toolbar"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.icon_dir = os.path.join(self.plugin_dir, "icons")

        self.actions: list[QAction] = []
        self.menu: QMenu | None = None
        self.toolbar: QToolBar | None = None
        self._dock = None

    # ───────────────────────── QGIS lifecycle ─────────────────────────

    def initGui(self) -> None:
        self.menu = QMenu(self.MENU_NAME)
        self.iface.mainWindow().menuBar().addMenu(self.menu)

        self.toolbar = QToolBar(self.TOOLBAR_NAME)
        self.toolbar.setObjectName("O2VizToolbar")
        self.iface.addToolBar(self.toolbar)

        self.panel_action = self._add_action(
            os.path.join(self.icon_dir, "icon.png"),
            "02viz Studio",
            self._toggle_dock,
            checkable=True,
            status_tip="Open or close the 02viz visualization studio",
        )
        self.menu.addSeparator()
        self._add_action(
            ":/images/themes/default/mActionHelpContents.svg",
            "About",
            self._show_about,
            add_to_toolbar=False,
        )

    def unload(self) -> None:
        if self._dock:
            self.iface.removeDockWidget(self._dock)
            self._dock.deleteLater()
            self._dock = None
        for action in self.actions:
            self.iface.removePluginMenu(self.MENU_NAME, action)
        if self.toolbar:
            del self.toolbar
        if self.menu:
            self.menu.deleteLater()

    # ───────────────────────── Studio dock ─────────────────────────

    def _toggle_dock(self) -> None:
        if self._dock is None:
            try:
                from .dialogs.dock import StudioDockWidget

                self._dock = StudioDockWidget(self.iface, self.icon_dir, self.iface.mainWindow())
                self._dock.setObjectName("O2VizDock")
                self._dock.visibilityChanged.connect(self.panel_action.setChecked)
                self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)
            except Exception as exc:
                QMessageBox.critical(self.iface.mainWindow(), PLUGIN_TITLE,
                                     f"Could not create the studio panel:\n{exc}")
                self.panel_action.setChecked(False)
                return
        self._dock.setVisible(not self._dock.isVisible())
        if self._dock.isVisible():
            self._dock.raise_()

    # ───────────────────────── Helpers ─────────────────────────

    def _add_action(self, icon_path, text, callback, *, add_to_toolbar=True,
                    add_to_menu=True, checkable=False, status_tip=None) -> QAction:
        action = QAction(QIcon(icon_path), text, self.iface.mainWindow())
        action.triggered.connect(callback)
        action.setCheckable(checkable)
        if status_tip:
            action.setStatusTip(status_tip)
        if add_to_toolbar and self.toolbar:
            self.toolbar.addAction(action)
        if add_to_menu and self.menu:
            self.menu.addAction(action)
        self.actions.append(action)
        return action

    def _show_about(self) -> None:
        QMessageBox.about(
            self.iface.mainWindow(),
            PLUGIN_TITLE,
            "<h3>02viz</h3>"
            "<p>Geospatial Visualization Studio — multi-engine charts "
            "from QGIS layers and external data.</p>"
            "<p><a href='https://github.com/YusufEminoglu/zero2viz'>"
            "github.com/YusufEminoglu/zero2viz</a></p>",
        )
