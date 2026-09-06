# -*- coding: utf-8 -*-
"""Small dependency-free helpers for safe chart publishing."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager, suppress


def ensure_extension(path: str, extension: str) -> str:
    """Append *extension* unless *path* already ends with it, case-insensitively."""
    suffix = extension if extension.startswith(".") else f".{extension}"
    return path if path.lower().endswith(suffix.lower()) else f"{path}{suffix}"


@contextmanager
def atomic_output(output_path: str):
    """Publish a sibling temporary file only after the writer succeeds."""
    final_path = os.path.abspath(output_path)
    folder = os.path.dirname(final_path)
    if not os.path.isdir(folder):
        raise ValueError(f"Output folder does not exist: {folder}")
    extension = os.path.splitext(final_path)[1]
    fd, temporary_path = tempfile.mkstemp(
        prefix=".zero2viz-export-", suffix=extension, dir=folder)
    os.close(fd)
    with suppress(OSError):
        os.remove(temporary_path)
    try:
        yield temporary_path
        if not os.path.isfile(temporary_path):
            raise ValueError("The chart writer did not create an output file.")
        if os.path.getsize(temporary_path) <= 0:
            raise ValueError("The chart writer created an empty output file.")
        os.replace(temporary_path, final_path)
    finally:
        with suppress(OSError):
            os.remove(temporary_path)


def atomic_write_text(output_path: str, content: str) -> int:
    """Write UTF-8 text atomically and return the published byte size."""
    with atomic_output(output_path) as temporary_path:
        with open(temporary_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    return os.path.getsize(os.path.abspath(output_path))


def human_size(size: int) -> str:
    """Compact deterministic file-size label for completion messages."""
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{size} B"
