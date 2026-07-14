# -*- coding: utf-8 -*-
"""Optional-dependency detection.

The studio works out of the box with zero Python dependencies (the JS engines
are vendored). *Advanced* engines — matplotlib/seaborn, plotnine, R/ggplot2 —
are optional: this module reports what's present and, when something is
missing, hands back the exact ``pip`` command the user can run themselves. It
never shells out to pip or installs anything — a QGIS plugin must not execute
package managers, and the studio stays offline and side-effect free.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys

# advanced engine id → pip packages it needs (R is not a pip install)
ENGINE_PIP_REQUIREMENTS: dict[str, list[str]] = {
    "matplotlib": ["matplotlib", "seaborn"],
    "plotnine": ["plotnine"],
}
# module name to import-probe per pip package (usually identical)
_IMPORT_NAME = {"scikit-learn": "sklearn"}


def library_available(module_name: str) -> bool:
    """True if ``module_name`` can be imported (no actual import performed)."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _probe_name(package: str) -> str:
    return _IMPORT_NAME.get(package, package.replace("-", "_"))


def missing_packages(packages: list[str]) -> list[str]:
    """Subset of ``packages`` whose import module is not available."""
    return [p for p in packages if not library_available(_probe_name(p))]


def engine_requirements_met(engine_id: str) -> bool:
    reqs = ENGINE_PIP_REQUIREMENTS.get(engine_id, [])
    return not missing_packages(reqs)


def r_available() -> bool:
    """True if an Rscript executable is on PATH (for the ggplot2 engine)."""
    return shutil.which("Rscript") is not None


def install_command(packages: list[str]) -> list[str]:
    """The exact argv the user can run themselves to install ``packages`` into
    the QGIS interpreter (shown, never executed — the studio does not shell
    out to pip)."""
    return [sys.executable, "-m", "pip", "install", "--user", *packages]


def install_command_str(packages: list[str]) -> str:
    """``install_command`` as a single copy-pasteable command line."""
    return " ".join(install_command(packages))
