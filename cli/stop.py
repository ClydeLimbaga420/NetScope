"""Stop the running local NetScope web UI from the command line."""

from __future__ import annotations

import http.cookiejar
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import config

_TOKEN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def _lock_path() -> Path:
    return config.data_dir() / "web-ui.json"


def read_lock() -> dict[str, Any] | None:
    """Read and validate the running instance's port/boot token record."""

    try:
        data = json.loads(_lock_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    port = data.get("port")
    boot_token = data.get("boot_token")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return None
    if (
        not isinstance(boot_token, str)
        or not boot_token
        or len(boot_token) > 256
        or not set(boot_token) <= _TOKEN_CHARS
    ):
        return None
    return {"port": port, "boot_token": boot_token}


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def stop_running_ui() -> str:
    """Ask the running instance to shut down.

    Returns ``"stopped"``, ``"not_running"``, or ``"error"``.
    """

    lock = read_lock()
    if lock is None or not _port_open(lock["port"]):
        return "not_running"

    origin = f"http://127.0.0.1:{lock['port']}"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )
    try:
        with opener.open(f"{origin}/__boot__?token={lock['boot_token']}", timeout=3) as response:
            response.read()
        with opener.open(f"{origin}/__session__", timeout=3) as response:
            session = json.loads(response.read().decode("utf-8"))
        token = session.get("token")
        if not isinstance(token, str) or not token:
            return "error"
        request = urllib.request.Request(
            f"{origin}/api/shutdown",
            data=json.dumps({}).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-NetScope-Token": token,
                "Origin": origin,
            },
        )
        with opener.open(request, timeout=3) as response:
            response.read()
            if response.status != 200:
                return "error"
        return "stopped"
    except (OSError, urllib.error.URLError, ValueError, TypeError, KeyError):
        return "error"
