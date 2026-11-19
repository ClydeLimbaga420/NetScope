"""Native pywebview/WebView2 window host for the local web UI."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
from typing import Any

WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_SPI_GETWORKAREA = 0x0030
_WINDOW_MARGIN = 24
_MAX_WINDOW_SIZE = (1280, 860)
_MIN_WINDOW_SIZE = (900, 600)


def _primary_work_area() -> tuple[int, int, int, int]:
    """Return the primary monitor work area as left, top, right, bottom."""

    if os.name != "nt":
        raise OSError("the Windows work area is unavailable")

    rect = ctypes.wintypes.RECT()
    user32 = ctypes.windll.user32
    if not user32.SystemParametersInfoW(
        _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
    ):
        raise ctypes.WinError()
    return rect.left, rect.top, rect.right, rect.bottom


def _window_geometry(
    work_area: tuple[int, int, int, int],
) -> tuple[int, int, int, int, tuple[int, int]]:
    """Calculate centered, screen-bounded window geometry and minimum size."""

    left, top, right, bottom = work_area
    work_width = right - left
    work_height = bottom - top
    if work_width <= 0 or work_height <= 0:
        raise ValueError("invalid monitor work area")

    width = min(_MAX_WINDOW_SIZE[0], max(1, work_width - 2 * _WINDOW_MARGIN))
    height = min(_MAX_WINDOW_SIZE[1], max(1, work_height - 2 * _WINDOW_MARGIN))
    x = left + (work_width - width) // 2
    y = top + (work_height - height) // 2
    min_size = (min(_MIN_WINDOW_SIZE[0], width), min(_MIN_WINDOW_SIZE[1], height))
    return x, y, width, height, min_size


def _webview2_version() -> str | None:
    """Return the installed WebView2 runtime version, or None."""

    if os.name != "nt":
        return None

    import winreg

    keys = (
        (
            winreg.HKEY_CURRENT_USER,
            rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}",
        ),
        (
            winreg.HKEY_LOCAL_MACHINE,
            rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}",
        ),
        (
            winreg.HKEY_LOCAL_MACHINE,
            rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}",
        ),
    )
    for root, path in keys:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        if isinstance(value, str) and value:
            return value
    return None


def webview2_available() -> bool:
    """True when a WebView2 runtime newer than 0.0.0.0 is registered."""

    version = _webview2_version()
    if not version:
        return False
    parts = version.split(".")[:4]
    if len(parts) < 4:
        return False
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return False
    return any(number > 0 for number in numbers)


def run_native_window(boot_url: str, logger: Any | None = None) -> bool:
    """Open the NetScope window and block until it closes."""

    if not webview2_available():
        return False
    try:
        geometry = _window_geometry(_primary_work_area())
    except (OSError, ValueError):
        return False
    try:
        import webview
    except Exception:
        return False
    if logger is not None:
        logger.event("window_create", source="web")
    try:
        x, y, width, height, min_size = geometry
        webview.create_window(
            "NetScope",
            boot_url,
            x=x,
            y=y,
            width=width,
            height=height,
            min_size=min_size,
        )
        if logger is not None:
            logger.event("window_started", source="web")
        try:
            webview.start(gui="edgechromium", debug=False)
        finally:
            destroy = getattr(webview, "destroy_window", None)
            if callable(destroy):
                try:
                    destroy()
                except Exception:
                    pass
    except Exception:
        return False
    if logger is not None:
        logger.event("window_closed", source="web")
    return True
