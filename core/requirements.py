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
import os
import shlex
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


def _is_python_binary(path: str) -> bool:
    name = os.path.basename(path or "").lower()
    return name.startswith("python") and not name.startswith("pythonw")


def python_executable() -> str:
    """The Python interpreter QGIS runs plugins in.

    Inside the QGIS desktop application ``sys.executable`` is the QGIS program
    itself (``qgis-bin.exe`` / ``qgis-ltr-bin.exe`` on Windows, the app binary
    on macOS), so ``sys.executable -m pip`` would start QGIS, not pip. The
    interpreter lives under ``sys.exec_prefix`` instead (OSGeo4W:
    ``apps\\Python3xx\\python.exe``; standalone installers alike)."""
    exe = sys.executable or ""
    if _is_python_binary(exe):
        return exe
    prefix = sys.exec_prefix or sys.prefix or ""
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    if os.name == "nt":
        candidates = [os.path.join(prefix, "python.exe"),
                      os.path.join(prefix, f"python{sys.version_info.major}.exe")]
    else:
        candidates = [os.path.join(prefix, "bin", f"python{ver}"),
                      os.path.join(prefix, "bin", f"python{sys.version_info.major}"),
                      os.path.join(prefix, "bin", "python")]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    found = shutil.which(f"python{ver}") or shutil.which("python3") or shutil.which("python")
    return found or ("python" if os.name == "nt" else "python3")


def install_command(packages: list[str]) -> list[str]:
    """The exact argv the user can run themselves to install ``packages`` into
    the QGIS interpreter (shown, never executed — the studio does not shell
    out to pip)."""
    return [python_executable(), "-m", "pip", "install", "--user", *packages]


def _quote(arg: str) -> str:
    if os.name == "nt":
        return f'"{arg}"' if (not arg or any(c in arg for c in ' \t&()^|<>')) else arg
    return shlex.quote(arg)


def install_command_str(packages: list[str]) -> str:
    """``install_command`` as a single copy-pasteable command line (paths with
    spaces quoted, e.g. ``"C:\\Program Files\\QGIS 3.44\\apps\\Python312\\python.exe"``)."""
    return " ".join(_quote(a) for a in install_command(packages))
