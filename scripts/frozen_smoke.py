"""Smoke-test a built (frozen) NetScope executable.

Launches ``NetScope.exe gui --no-browser --port N`` with an isolated
``LOCALAPPDATA``, opens the real boot URL with a cookie jar, checks the served
dashboard, CSS and ``/api/status``, then asks the server to shut down. Exit code
is 0 only when every check passes.

Usage:
    python scripts/frozen_smoke.py --exe dist/NetScope.exe
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_line(process: subprocess.Popen, timeout: float) -> str:
    if process.stdout is None:
        return ""
    lines: queue.Queue[str] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            lines.put(process.stdout.readline())
        except Exception:
            lines.put("")

    threading.Thread(target=read, daemon=True).start()
    try:
        return lines.get(timeout=timeout).strip()
    except queue.Empty:
        return ""


def _opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar)
    )


def _get(opener, url: str, timeout: float = 5.0) -> tuple[int, bytes]:
    with opener.open(url, timeout=timeout) as response:
        return response.status, response.read()


def _post(opener, url: str, payload: dict, token: str, origin: str) -> int:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-NetScope-Token": token,
            "Origin": origin,
        },
    )
    with opener.open(request, timeout=5) as response:
        response.read()
        return response.status


def run(exe: Path) -> list[str]:
    if not exe.is_file():
        raise SystemExit(f"executable not found: {exe}")

    checks: list[str] = []
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="netscope-frozen-") as temp:
        env = os.environ.copy()
        env["LOCALAPPDATA"] = temp
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            [str(exe), "gui", "--no-browser", "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        origin = f"http://127.0.0.1:{port}"
        token = None
        shutdown_accepted = False
        try:
            line = _read_line(process, timeout=60)
            expected_prefix = f"http://127.0.0.1:{port}/__boot__?"
            assert line.startswith(expected_prefix), f"unexpected boot line: {line!r}"
            checks.append("boot URL published")

            opener = _opener()
            status, body = _get(opener, line)
            text = body.decode("utf-8", errors="replace")
            assert status == 200, f"dashboard status {status}"
            assert "NetScope" in text, "dashboard missing product name"
            checks.append("dashboard served")

            status, css = _get(opener, f"http://127.0.0.1:{port}/static/css/style.css")
            assert status == 200 and len(css) > 1000, "local stylesheet missing"
            checks.append("bundled stylesheet served")

            _, session_body = _get(opener, f"http://127.0.0.1:{port}/__session__")
            token = json.loads(session_body.decode("utf-8"))["token"]
            status, status_body = _get(
                opener,
                f"http://127.0.0.1:{port}/api/status",
                timeout=30.0,
            )
            payload = json.loads(status_body.decode("utf-8"))
            assert status == 200 and isinstance(payload, dict) and payload, "status API empty"
            checks.append("status API served")

            status, devices_body = _get(
                opener,
                f"http://127.0.0.1:{port}/api/devices",
                timeout=15.0,
            )
            devices = json.loads(devices_body.decode("utf-8"))
            assert status in {200, 202}, f"devices API status {status}"
            if status == 202:
                assert devices.get("state") == "pending", "devices API pending state missing"
            else:
                assert isinstance(devices.get("devices"), list), (
                    "devices API payload invalid"
                )
            checks.append("devices API served")

            status = _post(
                opener, f"{origin}/api/shutdown", {"action": "frozen-smoke"}, token, origin
            )
            assert status == 200, f"shutdown status {status}"
            shutdown_accepted = True
            checks.append("shutdown accepted")

            process.wait(timeout=15)
            if process.returncode != 0:
                raise AssertionError(f"process exit code {process.returncode}")
            checks.append("process exited cleanly")

            rest = ""
            if process.stdout is not None:
                try:
                    rest = process.stdout.read() or ""
                except (OSError, ValueError):
                    rest = ""
            lowered = rest.lower()
            assert "development server" not in lowered, f"werkzeug banner in output: {rest!r}"
            assert "serving flask app" not in lowered, f"flask banner in output: {rest!r}"
            checks.append("quiet console")

            log = Path(temp) / "NetScope" / "logs" / "netscope.log"
            assert log.is_file(), f"structured log missing: {log}"
            records = [
                json.loads(row)
                for row in log.read_text(encoding="utf-8", errors="replace").splitlines()
                if row.strip()
            ]
            assert records, "structured log is empty"
            assert all("event" in record and "ts" in record for record in records)
            assert any(
                record.get("fields", {}).get("source") == "web" for record in records
            ), "no source:web records in structured log"
            checks.append("structured web logging")
            assert any(
                record.get("event") == "oui_map_loaded"
                and record.get("fields", {}).get("prefix_count", 0) > 0
                for record in records
            ), "OUI map load was not recorded"
            checks.append("bundled OUI resource loaded")

            lock = Path(temp) / "NetScope" / "web-ui.json"
            assert not lock.exists(), f"port lock not removed: {lock}"
            checks.append("port lock removed")
        finally:
            if process.poll() is None and token and not shutdown_accepted:
                try:
                    shutdown_accepted = (
                        _post(
                            opener,
                            f"{origin}/api/shutdown",
                            {"action": "frozen-smoke-cleanup"},
                            token,
                            origin,
                        )
                        == 200
                    )
                except (OSError, urllib.error.URLError) as exc:
                    print(
                        f"frozen smoke cleanup shutdown failed: {exc}",
                        file=sys.stderr,
                    )
            if process.poll() is None and shutdown_accepted:
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=Path("dist/NetScope.exe"))
    args = parser.parse_args(argv)
    try:
        checks = run(args.exe)
    except Exception as exc:  # noqa: BLE001 - smoke tool reports one line
        print(f"frozen smoke FAILED: {exc}", file=sys.stderr)
        return 1
    for check in checks:
        print(f"ok - {check}")
    print(f"frozen smoke passed ({len(checks)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
