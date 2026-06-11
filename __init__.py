"""02viz - Geospatial Visualization Studio: QGIS plugin entry point.

NOTE: this package name starts with a digit, so it can never be imported
with a literal ``import 02viz`` statement. QGIS loads plugins by string
(``__import__(packageName)``), which works fine — but every import inside
this package MUST be relative (``from .module import X``).
"""
from .main_plugin import O2VizPlugin


def classFactory(iface):
    return O2VizPlugin(iface)
