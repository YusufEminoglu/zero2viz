# -*- coding: utf-8 -*-
"""Chart engine registry. Engines are constructed lazily and only once."""
from __future__ import annotations

_ENGINES = None


def engines():
    global _ENGINES
    if _ENGINES is None:
        from .echarts import EChartsEngine
        from .mpl import MatplotlibEngine
        from .plotly import PlotlyEngine
        from .vegalite import VegaLiteEngine

        # matplotlib is the optional, publication-grade static engine; its
        # constructor is cheap (no matplotlib import until render), so listing
        # it here never slows QGIS startup
        _ENGINES = [EChartsEngine(), PlotlyEngine(), VegaLiteEngine(),
                    MatplotlibEngine()]
    return _ENGINES


def default_engine():
    return engines()[0]
