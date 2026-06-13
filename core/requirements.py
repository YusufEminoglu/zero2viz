# -*- coding: utf-8 -*-
"""Optional-dependency detection and on-demand install.

The studio works out of the box with zero Python dependencies (the JS engines
are vendored). *Advanced* engines — matplotlib/seaborn, plotnine, R/ggplot2 —
are optional: this module reports what's present and, on the user's explicit
click, installs the missing Python libraries into the QGIS interpreter's
user site-packages (``python -m pip install --user``). Never auto-installs.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
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
    """The exact argv used to install — also shown to the user before running."""
    return [sys.executable, "-m", "pip", "install", "--user", *packages]


def run_pip_install(packages: list[str], timeout: int = 900) -> tuple[bool, str]:
    """Install ``packages`` into the QGIS interpreter's user site-packages.

    Returns ``(ok, combined_log)``. Best-effort and fully guarded — a failed
    install never raises, it just reports the log so the dialog can show it.
    """
    if not packages:
        return True, "nothing to install"
    cmd = install_command(packages)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # subprocess failure, timeout, missing pip…
        return False, f"$ {' '.join(cmd)}\n{exc}"
    log = f"$ {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}".strip()
    return proc.returncode == 0, log
