from __future__ import annotations

import os
import sys
from typing import Any


def configure_utf8_stdio(stdout: Any | None = None, stderr: Any | None = None) -> None:
    """Prefer UTF-8 console IO on Windows and other local shells."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    for stream in (stdout or sys.stdout, stderr or sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass
