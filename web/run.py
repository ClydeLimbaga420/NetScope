"""Create app and run the local web UI server."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from web.security import TOKEN_PARAM
from web.server import WebState, create_app


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _open_url(url: str) -> None:
    # prefer app mode Edge/Chrome if available
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
            import subprocess
            subprocess.Popen([exe, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            continue
    try:
        webbrowser.open(url)
    except Exception:
        pass


def run_web_ui(port: int | None = None, no_browser: bool = False) -> int:
    state = WebState(mode="web")
    app = create_app(state)
    port = int(port) if port else _find_free_port()
    state.port = port
    boot_url = f"http://127.0.0.1:{port}/__boot__?{TOKEN_PARAM}={state.security.boot_token}"

    def monitor() -> None:
        while not state.shutdown_event.is_set():
            if state.should_shutdown():
                state.logger.event("server_shutdown", source="web", reason="heartbeat_timeout")
                state.shutdown_event.set()
                # werkzeug shutdown via raising in request context is messy; os._exit is harsh but ensures exit
                os._exit(0)
            time.sleep(2)

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
    return 0
