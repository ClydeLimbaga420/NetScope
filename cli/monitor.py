"""Live monitoring dashboard for the NetScope CLI."""

from __future__ import annotations

import signal
import sys
import time
from datetime import datetime
from typing import Any

from cli.context import CliContext
from cli.exit_codes import OK, INTERRUPTED
from cli.render import Colorizer, render_result, summary_lines
from core.engine import DiagnosticEngine
from core.models import CheckResult, Status


class LiveDashboard:
    """ANSI-based live updating dashboard."""

    def __init__(self, ctx: CliContext, interval: float = 3.0):
        self.ctx = ctx
        self.interval = interval
        self.color = ctx.color
        self.running = False
        self.last_report = None
        self.last_update = None
        self.engine = DiagnosticEngine(
            runner=ctx.runner,
            ps=ctx.ps,
            logger=ctx.logger,
        )
        self._setup_signals()

    def _setup_signals(self) -> None:
        def handler(signum, frame):
            self.running = False
        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handler)

    def _clear_screen(self) -> None:
        self.ctx.stdout.write("\x1b[2J\x1b[H")
        self.ctx.stdout.flush()

    def _move_cursor(self, row: int, col: int = 1) -> None:
        self.ctx.stdout.write(f"\x1b[{row};{col}H")
        self.ctx.stdout.flush()

    def _hide_cursor(self) -> None:
        self.ctx.stdout.write("\x1b[?25l")
        self.ctx.stdout.flush()

    def _show_cursor(self) -> None:
        self.ctx.stdout.write("\x1b[?25h")
        self.ctx.stdout.flush()

    def _save_cursor(self) -> None:
        self.ctx.stdout.write("\x1b[s")
        self.ctx.stdout.flush()

    def _restore_cursor(self) -> None:
        self.ctx.stdout.write("\x1b[u")
        self.ctx.stdout.flush()

    def _render_header(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        interval_str = f"Interval: {self.interval:.1f}s"
        self.ctx.stdout.write(
            self.color.paint(f"NetScope Live Monitor  |  {now}  |  {interval_str}  |  Press 'q' to quit", bold=True)
        )
        self.ctx.stdout.write("\n")
        self.ctx.stdout.write(self.color.paint("─" * 80))
        self.ctx.stdout.write("\n\n")

    def _render_overall_status(self) -> None:
        if not self.last_report:
            self.ctx.stdout.write("Collecting initial data...\n")
            return

        overall = self.last_report.overall_status
        counts = {
            Status.PASS: 0,
            Status.WARN: 0,
            Status.FAIL: 0,
            Status.SKIP: 0,
            Status.ERROR: 0,
        }
        for r in self.last_report.results:
            counts[r.status] = counts.get(r.status, 0) + 1

        status_line = (
            f"Overall: {self.color.paint(overall.value.upper(), bold=True)}  "
            f"({counts[Status.PASS]} pass, {counts[Status.WARN]} warn, "
            f"{counts[Status.FAIL]} fail, {counts[Status.SKIP]} skip"
        )
        if counts[Status.ERROR]:
            status_line += f", {counts[Status.ERROR]} error"
        status_line += ")"

        self.ctx.stdout.write(status_line + "\n")

        if self.last_report.first_failing_layer:
            from core.models import LAYER_LABELS
            layer_label = LAYER_LABELS.get(self.last_report.first_failing_layer, self.last_report.first_failing_layer.value)
            self.ctx.stdout.write(
                f"First failing layer: {self.color.paint(layer_label, 'yellow')}\n"
            )

        if self.last_update:
            self.ctx.stdout.write(f"Last update: {self.last_update.strftime('%H:%M:%S')}\n")
        self.ctx.stdout.write("\n")

    def _render_layer_status(self) -> None:
        if not self.last_report:
            return

        from core.models import LAYER_ORDER, LAYER_LABELS

        self.ctx.stdout.write(self.color.paint("Layer Status:", bold=True) + "\n")

        for layer in LAYER_ORDER:
            layer_results = [r for r in self.last_report.results if r.layer is layer]
            if not layer_results:
                continue

            worst = Status.PASS
            for r in layer_results:
                if r.status.severity > worst.severity:
                    worst = r.status

            label = LAYER_LABELS.get(layer, layer.value)
            status_color = {
                Status.PASS: "green",
                Status.WARN: "yellow",
                Status.FAIL: "red",
                Status.ERROR: "red",
                Status.SKIP: "cyan",
            }.get(worst, "white")

            self.ctx.stdout.write(f"  {label:<20} ")
            self.ctx.stdout.write(self.color.paint(f"[{worst.value.upper():5}]", status_color))
            self.ctx.stdout.write("\n")

        self.ctx.stdout.write("\n")

    def _render_key_findings(self) -> None:
        if not self.last_report:
            return

        failing = [
            r for r in self.last_report.results
            if r.status.severity >= Status.WARN.severity
        ][:10]

        if not failing:
            self.ctx.stdout.write("No warnings or failures.\n")
            return

        self.ctx.stdout.write(self.color.paint("Key Findings:", bold=True) + "\n")
        for result in failing:
            for line in render_result(result, self.color, verbose=False):
                self.ctx.stdout.write(f"  {line}\n")
        self.ctx.stdout.write("\n")

    def _render_footer(self) -> None:
        self.ctx.stdout.write(self.color.paint("─" * 80))
        self.ctx.stdout.write("\n")
        self.ctx.stdout.write("Commands: [q] Quit  [r] Refresh now  [i] Interval  [l] Layers  [f] Findings\n")

    def _render_full(self) -> None:
        self._save_cursor()
        self._move_cursor(1, 1)
        self._render_header()
        self._render_overall_status()
        self._render_layer_status()
        self._render_key_findings()
        self._render_footer()
        self._restore_cursor()

    def _collect_input(self) -> str | None:
        """Non-blocking input check."""
        import msvcrt
        if msvcrt.kbhit():
            key = msvcrt.getwch()
            return key.lower()
        return None

    def _handle_key(self, key: str) -> bool:
        """Handle key press. Returns True to continue, False to exit."""
        if key == "q":
            return False
        elif key == "r":
            self._run_diagnose()
            self._render_full()
        elif key == "i":
            self._prompt_interval()
        elif key == "l":
            self._toggle_layer_detail()
        elif key == "f":
            self._toggle_findings_detail()
        return True

    def _prompt_interval(self) -> None:
        self._show_cursor()
        self._move_cursor(25, 1)
        self.ctx.stdout.write("\x1b[KNew interval (seconds): ")
        self.ctx.stdout.flush()
        try:
            line = sys.stdin.readline()
            if line:
                val = float(line.strip())
                if val >= 0.5:
                    self.interval = val
        except (ValueError, EOFError):
            pass
        self._hide_cursor()
        self._render_full()

    def _toggle_layer_detail(self) -> None:
        pass

    def _toggle_findings_detail(self) -> None:
        pass

    def _run_diagnose(self) -> None:
        try:
            self.last_report = self.engine.diagnose(mode="monitor")
            self.last_update = datetime.now()
        except Exception as exc:
            self.ctx.logger.error("monitor_diagnose_failed", exc_info=True, error=str(exc))
            self.last_report = None

    def run(self) -> int:
        self._hide_cursor()
        self._clear_screen()

        self._run_diagnose()
        self._render_full()

        self.running = True
        last_run = time.monotonic()

        while self.running:
            now = time.monotonic()
            elapsed = now - last_run

            key = self._collect_input()
            if key:
                if not self._handle_key(key):
                    break

            if elapsed >= self.interval:
                self._run_diagnose()
                self._render_full()
                last_run = time.monotonic()

            time.sleep(0.1)

        self._show_cursor()
        self._clear_screen()
        self.ctx.stdout.write("Monitor stopped.\n")
        return OK


def run_monitor(ctx: CliContext, interval: float = 3.0) -> int:
    """Entry point for the monitor command."""
    if not ctx.color.enabled and not ctx.color.stream.isatty():
        ctx.err("Monitor mode requires a TTY with color support.")
        return INTERRUPTED

    dashboard = LiveDashboard(ctx, interval=interval)
    return dashboard.run()