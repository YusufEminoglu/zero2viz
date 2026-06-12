"""02viz - Geospatial Visualization Studio: QGIS plugin entry point.

The package directory is ``zero2viz`` — the QGIS Plugin Hub requires the
zip's top-level directory to be a valid Python identifier, so the original
``02viz`` (digit-first) was rejected at upload. The displayed plugin name
stays "02viz". Convention kept from the digit-first era: every import
inside this package is relative (``from .module import X``).
"""
from .main_plugin import O2VizPlugin


def classFactory(iface):
    return O2VizPlugin(iface)
