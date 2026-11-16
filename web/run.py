"""Create app and run the local web UI server."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import BinaryIO
from werkzeug.serving import make_server

import config
from web.security import TOKEN_PARAM
from web.server import WebState, create_app
from web.window import run_native_window, webview2_available


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _lock_path() -> Path:
    return config.data_dir() / "web-ui.json"


def _instance_lock_path() -> Path:
    return config.data_dir() / "web-ui.lock"


def _acquire_instance_lock() -> BinaryIO | None:
    path = _instance_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _release_instance_lock(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    handle.close()


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
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temp:
            temp.write(json.dumps(data))
            temp.flush()
            os.fsync(temp.fileno())
            temp_path = Path(temp.name)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _remove_lock(pid: int | None = None) -> None:
    try:
        path = _lock_path()
        data = _read_lock()
        if data and (pid is None or data.get("pid") == int(pid)):
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _launch_mode(no_browser: bool, browser: bool) -> str:
    if no_browser:
        return "headless"
    if browser:
        return "browser"
    return "window"


def _show_existing(url: str, mode: str, state: WebState) -> bool:
    if mode == "headless":
        print(url, flush=True)
        return True
    if mode == "window":
        if run_native_window(url):
            return True
        state.logger.warning("webview_unavailable", source="web")
        return _open_url(url)
    return _open_url(url)


def _acquire_lock_with_wait(timeout: float = 10.0) -> BinaryIO | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lock = _acquire_instance_lock()
        if lock is not None:
            return lock
        time.sleep(0.1)
    return None


def _run_window_session(state: WebState, srv: object, boot_url: str, print_url: bool) -> None:
    server_thread = threading.Thread(target=srv.serve_forever, daemon=True)
    server_thread.start()
    if print_url:
        print(boot_url, flush=True)
    if not run_native_window(boot_url):
        state.logger.warning("webview_unavailable", source="web")
        _open_url(boot_url)
    state.shutdown_event.wait()


def _existing_instance_url(lock: dict | None) -> str | None:
    if not isinstance(lock, dict):
        return None
    port = lock.get("port")
    boot_token = lock.get("boot_token")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return None
    if not isinstance(boot_token, str) or not boot_token or len(boot_token) > 256:
        return None
    if not _port_open(port):
        return None
    health_url = f"http://127.0.0.1:{port}/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(health_url, timeout=1) as response:
            if response.status != 200 or response.read(16).strip() != b"ok":
                return None
    except (OSError, urllib.error.URLError):
        return None
    return f"http://127.0.0.1:{port}/__boot__?{TOKEN_PARAM}={boot_token}"


def _open_url(url: str) -> bool:
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
            return True
        except Exception:
            continue
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def _monitor(state: WebState, interval: float = 2.0) -> None:
    while True:
        if state.shutdown_event.wait(interval):
            # explicit request (POST /api/shutdown or /api/elevate): give the
            # HTTP response a moment to flush before exiting the process.
            time.sleep(0.5)
            state.logger.event("server_shutdown", source="web", reason="api_request")
            _remove_lock(os.getpid())
            os._exit(0)
        if state.should_shutdown():
            state.logger.event("server_shutdown", source="web", reason="heartbeat_timeout")
            state.shutdown_event.set()
            _remove_lock(os.getpid())
            os._exit(0)


def run_web_ui(
    port: int | None = None,
    no_browser: bool = False,
    browser: bool = False,
    print_url: bool = False,
    replace: bool = False,
) -> int:
    mode = _launch_mode(no_browser, browser)

    if replace:
        instance_lock = _acquire_lock_with_wait(10.0)
        if instance_lock is None:
            logger = config.setup_logging("web", session_id="replace-wait")
            logger.error("elevate_takeover_timeout", source="web", timeout=10.0)
            return 1
    else:
        instance_lock = _acquire_instance_lock()

    if instance_lock is None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            url = _existing_instance_url(_read_lock())
            if url:
                if mode == "headless" or print_url:
                    print(url, flush=True)
                else:
                    state = WebState(mode="web")
                    _show_existing(url, mode, state)
                return 0
            time.sleep(0.1)
        return 1

    state = WebState(mode="web")
    try:
        app = create_app(state)
        port = int(port) if port else _find_free_port()
        state.port = port
        boot_url = f"http://127.0.0.1:{port}/__boot__?{TOKEN_PARAM}={state.security.boot_token}"

        try:
            srv = make_server("127.0.0.1", port, app, threaded=True)
        except SystemExit as exc:
            if exc.code != 1:
                raise
            state.logger.error("server_bind_failed", source="web", port=port, error="port unavailable")
            return 1
        except OSError as exc:
            state.logger.error("server_bind_failed", source="web", port=port, error=str(exc))
            return 1

        _write_lock(port, state.security.boot_token, os.getpid())

        threading.Thread(target=_monitor, args=(state,), daemon=True).start()

        state.logger.event("server_start", source="web", port=port)

        if mode == "window":
            if print_url:
                print(boot_url, flush=True)
            _run_window_session(state, srv, boot_url, print_url)
        elif mode == "browser":
            if print_url:
                print(boot_url, flush=True)
            threading.Timer(0.6, lambda: _open_url(boot_url)).start()
            srv.serve_forever()
        else:  # headless
            print(boot_url, flush=True)
            srv.serve_forever()
    except KeyboardInterrupt:
        if state is not None:
            state.logger.event("server_shutdown", source="web", reason="keyboard_interrupt")
    finally:
        _remove_lock(os.getpid())
        _release_instance_lock(instance_lock)
    return 0
