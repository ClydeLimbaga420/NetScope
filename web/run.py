"""Create app and run the local web UI server."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import config
from web.security import TOKEN_PARAM
from web.server import WebState, create_app


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _lock_path() -> Path:
    return config.data_dir() / "web-ui.json"


def _read_lock() -> dict | None:
    path = _lock_path()
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
            return True
    except Exception:
        return False


def _write_lock(port: int, boot_token: str, pid: int) -> None:
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"port": int(port), "boot_token": boot_token, "pid": int(pid), "ts": time.time()}
    path.write_text(json.dumps(data), encoding="utf-8")


def _remove_lock() -> None:
    try:
        _lock_path().unlink(missing_ok=True)
    except Exception:
        pass


def _open_url(url: str) -> None:
    candidates = []
    localapp = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pfx86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    for exe in [
        os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pfx86, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(localapp, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pfx86, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(localapp, "Google", "Chrome", "Application", "chrome.exe"),
    ]:
        if exe and os.path.exists(exe):
            candidates.append(exe)
    for exe in candidates:
        try:
            subprocess.Popen([exe, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            continue
    try:
        webbrowser.open(url)
    except Exception:
        pass


def run_web_ui(port: int | None = None, no_browser: bool = False) -> int:
    # single-instance: if a server for this user is already running, open it
    lock = _read_lock()
    if lock and _port_open(lock.get("port")):
        url = f"http://127.0.0.1:{int(lock['port'])}/__boot__?{TOKEN_PARAM}={lock.get('boot_token','')}"
        if no_browser:
            print(url)
        else:
            _open_url(url)
        return 0

    state = WebState(mode="web")
    app = create_app(state)
    port = int(port) if port else _find_free_port()
    state.port = port
    boot_url = f"http://127.0.0.1:{port}/__boot__?{TOKEN_PARAM}={state.security.boot_token}"
    _write_lock(port, state.security.boot_token, os.getpid())

    def monitor() -> None:
        while not state.shutdown_event.is_set():
            if state.should_shutdown():
                state.logger.event("server_shutdown", source="web", reason="heartbeat_timeout")
                state.shutdown_event.set()
                _remove_lock()
                os._exit(0)
            time.sleep(2)
        _remove_lock()

    threading.Thread(target=monitor, daemon=True).start()

    if not no_browser:
        threading.Timer(0.6, lambda: _open_url(boot_url)).start()
    else:
        print(boot_url)

    state.logger.event("server_start", source="web", port=port)
    try:
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        state.logger.event("server_shutdown", source="web", reason="keyboard_interrupt")
    finally:
        _remove_lock()
    return 0
