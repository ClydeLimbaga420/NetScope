"""Native pywebview/WebView2 window host for the local web UI."""

from __future__ import annotations

import os

WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


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


def run_native_window(boot_url: str) -> bool:
    """Open the NetScope window and block until it closes."""

    if not webview2_available():
        return False
    try:
        import webview
    except Exception:
        return False
    try:
        webview.create_window(
            "NetScope",
            boot_url,
            width=1280,
            height=860,
            min_size=(900, 600),
        )
        webview.start(gui="edgechromium", debug=False)
    except Exception:
        return False
    return True
