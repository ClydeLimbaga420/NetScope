"""Resource path helpers for development and PyInstaller onefile builds."""

from __future__ import annotations

import sys
from pathlib import Path


def bundle_root() -> Path:
    """Return the directory containing bundled resources.

    When frozen by PyInstaller this is ``sys._MEIPASS``; in development it is
    the project root so ``web/templates`` and ``web/static`` resolve normally.
    """

    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent


def web_root() -> Path:
    return bundle_root() / "web"
