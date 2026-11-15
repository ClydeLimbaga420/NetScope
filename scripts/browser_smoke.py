"""Headless-browser smoke test for the local web UI.

Requires Playwright (``pip install playwright``) and a Chromium-based browser.
Uses the installed Microsoft Edge channel first, then Playwright's bundled
Chromium. If neither is available the script prints a skip message and exits 0,
so CI can run it on hosts without a browser.

Usage:
    python scripts/browser_smoke.py [--python PYTHON] [--timeout SECONDS]
"""

from __future__ import annotations

import argparse
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_line(process: subprocess.Popen, timeout: float) -> str:
    lines: queue.Queue[str] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            lines.put(process.stdout.readline() if process.stdout else "")
        except Exception:
            lines.put("")

    threading.Thread(target=read, daemon=True).start()
    try:
        return lines.get(timeout=timeout).strip()
    except queue.Empty:
        return ""


def _launch_server(python: str, port: int, local_app_data: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["LOCALAPPDATA"] = local_app_data
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.Popen(
        [python, "-m", "cli", "gui", "--no-browser", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )


def run(python: str, timeout: float, screenshots: Path | None) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "SKIP: Playwright is not installed"

    if screenshots is not None:
        screenshots.mkdir(parents=True, exist_ok=True)

    root = Path(__file__).resolve().parents[1]
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="netscope-browser-") as temp:
        process = _launch_server(python, port, temp)
        try:
            boot_url = _read_line(process, timeout=60)
            if not boot_url.startswith(f"http://127.0.0.1:{port}/__boot__?"):
                raise AssertionError(f"unexpected boot URL: {boot_url!r}")

            with sync_playwright() as playwright:
                browser = None
                for options in ({"channel": "msedge"}, {}):
                    try:
                        browser = playwright.chromium.launch(headless=True, **options)
                        break
                    except Exception:  # browser/channel unavailable
                        continue
                if browser is None:
                    return "SKIP: no Chromium/Edge browser available"

                page = browser.new_page(viewport={"width": 1280, "height": 900})
                errors: list[str] = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(boot_url, wait_until="load", timeout=30000)
                page.wait_for_function(
                    "window.__netscope && window.__netscope.ready", timeout=15000
                )
                assert "NetScope" in page.title(), f"unexpected title: {page.title()!r}"
                assert page.locator("#main-content").is_visible()
                assert page.evaluate("document.styleSheets.length > 0")
                assert page.evaluate(
                    "window.NetScope && typeof window.NetScope.toast === 'function'"
                )
                assert page.locator("#toast-region").count() == 1

                layout = page.evaluate(
                    """() => {
                        const cards = document.querySelector('.cards');
                        const conn = document.querySelector('.card.connectivity');
                        const metrics = [...document.querySelectorAll('.cards > .card')]
                            .filter(card => !card.classList.contains('connectivity'));
                        const widths = metrics.map(card => card.getBoundingClientRect().width);
                        const labels = metrics.map(card => card.querySelector('.card-label'))
                            .filter(Boolean)
                            .map(label => ({
                                text: label.textContent.trim(),
                                wraps: label.scrollWidth > label.clientWidth + 1,
                            }));
                        return {
                            columns: getComputedStyle(cards).gridTemplateColumns
                                .split(' ').filter(Boolean).length,
                            connWidth: conn.getBoundingClientRect().width,
                            metricWidths: widths,
                            labels,
                        };
                    }"""
                )
                assert layout["columns"] >= 4, f"stat grid columns: {layout['columns']}"
                assert layout["metricWidths"] and min(layout["metricWidths"]) >= 180, layout
                assert layout["connWidth"] > max(layout["metricWidths"]) * 2, layout
                assert not any(label["wraps"] for label in layout["labels"]), layout
                if screenshots is not None:
                    page.screenshot(path=str(screenshots / "dashboard-1280.png"), full_page=True)

                page.set_viewport_size({"width": 480, "height": 900})
                page.locator("#nav-toggle").click()
                page.wait_for_function(
                    "document.querySelector('aside.sidebar').classList.contains('open')"
                )
                if screenshots is not None:
                    page.screenshot(path=str(screenshots / "mobile-drawer-480.png"), full_page=True)
                page.keyboard.press("Escape")
                page.wait_for_function(
                    "!document.querySelector('aside.sidebar').classList.contains('open')"
                )

                page.set_viewport_size({"width": 1280, "height": 900})
                page.locator('a[data-view="troubleshoot"]').click()
                page.wait_for_selector("#check-steps", state="visible")
                if screenshots is not None:
                    page.screenshot(
                        path=str(screenshots / "troubleshoot-1280.png"), full_page=True
                    )

                status = page.evaluate(
                    """async () => {
                        const token = window.__netscope && window.__netscope.token;
                        const response = await fetch('/api/shutdown', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-NetScope-Token': token || '',
                            },
                            body: '{}',
                        });
                        return response.status;
                    }"""
                )
                assert status == 200, f"shutdown status {status}"
                browser.close()

            if errors:
                raise AssertionError("page errors: " + "; ".join(errors))
            process.wait(timeout=15)
            if process.returncode != 0:
                raise AssertionError(f"server exit code {process.returncode}")
            lock = Path(temp) / "NetScope" / "web-ui.json"
            assert not lock.exists(), f"port lock not removed: {lock}"
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
    return (
        "Browser smoke passed (shell, session, CSS, stat layout, mobile drawer, "
        "Troubleshoot, shutdown)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--screenshots",
        type=Path,
        default=Path("artifacts/browser-smoke"),
        help="directory for dashboard/mobile/Troubleshoot screenshots",
    )
    parser.add_argument(
        "--no-screenshots", action="store_true", help="skip screenshot capture"
    )
    args = parser.parse_args(argv)
    screenshots = None if args.no_screenshots else args.screenshots
    try:
        result = run(args.python, args.timeout, screenshots)
    except Exception as exc:  # noqa: BLE001 - one-line browser report
        print(f"Browser smoke FAILED: {exc}", file=sys.stderr)
        return 1
    print(result)
    if screenshots is not None:
        print(f"Screenshots: {screenshots.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
