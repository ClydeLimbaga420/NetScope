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
from urllib.parse import urlsplit
from werkzeug.serving import make_server

import config
from web.security import TOKEN_PARAM
from web.server import WebState, create_app


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


def _release_instance_lock(handle: BinaryIO | None) -> None:
    if handle is None:
        return
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
    try:
        handle.close()
    except Exception:
        pass


def _restore_instance_lock(state: WebState) -> bool:
    if getattr(state, "instance_lock_handle", None) is not None:
        return True
    handle = _acquire_instance_lock()
    if handle is None:
        return False
    try:
        _write_lock(state.port, state.security.boot_token, os.getpid())
    except Exception:
        _release_instance_lock(handle)
        raise
    state.instance_lock_handle = handle
    return True


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


def _notify_elevate_handoff(
    callback_url: str,
    callback_token: str,
    port: int,
    boot_token: str,
) -> None:
    parsed_url = urlsplit(callback_url)
    if (
        parsed_url.scheme != "http"
        or parsed_url.hostname != "127.0.0.1"
        or parsed_url.path != "/__elevate_complete__"
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.port is None
        or not 1 <= parsed_url.port <= 65535
    ):
        raise ValueError("Elevation handoff callback must be a local NetScope URL.")

    payload = json.dumps({"port": int(port), "boot_token": boot_token}).encode("utf-8")
    request = urllib.request.Request(
        callback_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-NetScope-Handoff": callback_token,
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError(f"Elevation handoff callback returned HTTP {response.status}.")


def _monitor(state: WebState, interval: float = 2.0) -> None:
    while True:
        if state.shutdown_event.wait(interval):
            # explicit request (POST /api/shutdown): give the HTTP response a
            # moment to flush before exiting the process.
            time.sleep(0.5)
            state.logger.event("server_shutdown", source="web", reason="api_request")
            _remove_lock(os.getpid())
            os._exit(0)

        handoff = getattr(state, "elevate_handoff", None)
        if handoff and handoff.get("active"):
            if not handoff.get("url"):
                lock = _read_lock() or {}
                if int(lock.get("pid") or 0) != os.getpid():
                    url = _existing_instance_url(lock)
                    if url:
                        handoff["url"] = url
                        state.logger.event("elevate_handoff_ready", source="web", url=url)
            if handoff.get("url") and not handoff.get("shutdown_scheduled"):
                handoff["shutdown_scheduled"] = True
                threading.Timer(5.0, lambda: state.shutdown_event.set()).start()
            if not handoff.get("url") and time.monotonic() > float(handoff.get("deadline") or 0):
                handoff["error"] = "Timed out waiting for the elevated NetScope instance."
                handoff["active"] = False
                state.logger.error("elevate_handoff_timeout", source="web")
                try:
                    if not _restore_instance_lock(state):
                        state.logger.event(
                            "elevate_handoff_lock_restore_failed",
                            source="web",
                            reason="instance lock is held by another process",
                        )
                    else:
                        state.logger.event("elevate_handoff_lock_restored", source="web")
                except Exception as exc:  # noqa: BLE001
                    state.logger.error(
                        "elevate_handoff_lock_restore_failed",
                        source="web",
                        error=str(exc),
                        exc_info=True,
                    )
            continue

        if state.should_shutdown():
            state.logger.event("server_shutdown", source="web", reason="heartbeat_timeout")
            state.shutdown_event.set()
            _remove_lock(os.getpid())
            os._exit(0)


def run_web_ui(
    port: int | None = None,
    no_browser: bool = False,
    handoff_url: str | None = None,
    handoff_token: str | None = None,
) -> int:
    if bool(handoff_url) != bool(handoff_token):
        raise ValueError("Both elevation handoff URL and token are required.")

    instance_lock = _acquire_instance_lock()
    if instance_lock is None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            lock = _read_lock()
            url = _existing_instance_url(lock)
            if url and lock:
                if no_browser:
                    if sys.stdout is not None:
                        print(url)
                else:
                    _open_url(url)
                if handoff_url and handoff_token:
                    _notify_elevate_handoff(
                        handoff_url,
                        handoff_token,
                        int(lock["port"]),
                        str(lock["boot_token"]),
                    )
                return 0
            time.sleep(0.1)
        return 1

    state = None
    try:
        state = WebState(mode="web")
        app = create_app(state)
        port = int(port) if port else _find_free_port()
        state.port = port
        boot_url = f"http://127.0.0.1:{port}/__boot__?{TOKEN_PARAM}={state.security.boot_token}"

        # Bind before advertising anything. Werkzeug 3.x converts bind
        # OSErrors into print(strerror) + sys.exit(1) inside
        # BaseWSGIServer.__init__, so a failed bind surfaces as SystemExit(1),
        # not OSError; catch both so the failure is logged and returns
        # cleanly instead of escaping the CLI.
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

        state.instance_lock_handle = instance_lock
        _write_lock(port, state.security.boot_token, os.getpid())

        threading.Thread(target=_monitor, args=(state,), daemon=True).start()
        if handoff_url and handoff_token:
            try:
                _notify_elevate_handoff(
                    handoff_url,
                    handoff_token,
                    port,
                    state.security.boot_token,
                )
            except Exception as exc:
                state.logger.error(
                    "elevate_handoff_callback_failed",
                    source="web",
                    error=str(exc),
                    exc_info=True,
                )

        if not no_browser:
            threading.Timer(0.6, lambda: _open_url(boot_url)).start()
        elif sys.stdout is not None:
            print(boot_url, flush=True)

        state.logger.event("server_start", source="web", port=port)
        srv.serve_forever()
    except KeyboardInterrupt:
        if state is not None:
            state.logger.event("server_shutdown", source="web", reason="keyboard_interrupt")
    finally:
        handoff = getattr(state, "elevate_handoff", None) if state is not None else None
        if handoff and handoff.get("url"):
            _remove_lock(int(handoff.get("pid") or os.getpid()))
        else:
            _remove_lock(os.getpid())
        if state is not None:
            _release_instance_lock(getattr(state, "instance_lock_handle", None))
            state.instance_lock_handle = None
        else:
            _release_instance_lock(instance_lock)
    return 0
