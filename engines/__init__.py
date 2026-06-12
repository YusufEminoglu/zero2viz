# -*- coding: utf-8 -*-
"""Chart engine registry. Engines are constructed lazily and only once."""
from __future__ import annotations

_ENGINES = None


def engines():
    global _ENGINES
    if _ENGINES is None:
        from .echarts import EChartsEngine
        from .plotly import PlotlyEngine
        from .vegalite import VegaLiteEngine

        _ENGINES = [EChartsEngine(), PlotlyEngine(), VegaLiteEngine()]
    return _ENGINES


def default_engine():
    return engines()[0]
