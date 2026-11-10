"""Tkinter front end for NetScope.

The GUI contains no business logic: diagnosis goes through ``DiagnosticEngine``
and every fix goes through ``FixExecutor`` with the catalog, exactly like the
CLI. Rendering of outcomes reuses the plain-text render helpers so both front
ends show the same information.

Workers run in background threads and talk to the Tk event loop through a
queue; dialogs requested by the fix executor are marshalled through
:class:`gui.dialogs.DialogBridge` so confirmations still work while commands
execute.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk

import config

from cli.admin import admin_guidance, relaunch_elevated
from cli.render import (
    render_fix_outcome,
    render_report_text,
    render_unresolved_section,
)
from core.info import build_info
from core.logging_config import LOG_FILE_NAME, flush_logging
from core.models import LAYER_LABELS, LAYER_ORDER, CheckResult, DiagnosticReport, Status
from fixes.catalog import CatalogError, FixEntry
from fixes.executor import FixOutcome, PlanError
from fixes.if_unresolved import build_unresolved_sections, unresolved_section
from gui.dialogs import DialogBridge
from gui.launch import gui_relaunch_argv
from gui.runtime import GuiRuntime, build_runtime

_STATUS_LABELS = {
    Status.PASS: "PASS",
    Status.WARN: "WARN",
    Status.FAIL: "FAIL",
    Status.SKIP: "SKIP",
    Status.ERROR: "ERROR",
}


class LikelyCausesPanel(ttk.Frame):
    """Collapsed-by-default "Still not working? Likely causes" panel."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self._visible = False
        self._header = ttk.Button(
            self,
            text="Still not working? Likely causes  (click to show)",
            command=self.toggle,
        )
        self._header.pack(fill="x")
        self.body = tk.Text(self, height=12, wrap="word", state="disabled")
        self.body.pack_forget()

    def toggle(self) -> None:
        if self._visible:
            self.body.pack_forget()
        else:
            self.body.pack(fill="both", expand=True)
        self._visible = not self._visible

    def show(self, section: dict[str, Any]) -> None:
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        for line in render_unresolved_section(section):
            self.body.insert("end", line + "\n")
        self.body.configure(state="disabled")
        if not self._visible:
            self.toggle()

    def clear(self) -> None:
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.body.configure(state="disabled")


class NetScopeGui:
    """Main window: findings list, plain-language detail, guided fixes."""

    def __init__(self, root: tk.Tk, runtime: GuiRuntime, *, auto_confirm: bool = False) -> None:
        self.root = root
        self.runtime = runtime
        self.catalog = runtime.catalog
        self.auto_confirm = auto_confirm
        self.bridge = DialogBridge()
        self.bridge.handler = self._handle_dialog
        self._queue: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.report: DiagnosticReport | None = None
        self._last_snapshot: Any = None
        self._selected: CheckResult | None = None
        self._busy = False
        self._layer_vars: dict[str, tk.BooleanVar] = {}
        self._poll_after: str | None = None

        root.title("NetScope")
        root.geometry("1000x660")
        root.protocol("WM_DELETE_WINDOW", self.shutdown)
        self._build_layout()
        self._refresh_admin_label()
        self._poll_queue()
        runtime.logger.event("gui_start", session_id=runtime.session_id)

    # -- layout ---------------------------------------------------------------

    def _build_layout(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=(8, 4))

        self.run_button = ttk.Button(top, text="Run diagnosis", command=self.start_diagnosis)
        self.run_button.pack(side="left")
        self.export_button = ttk.Button(top, text="Export report", command=self.export_report)
        self.export_button.pack(side="left", padx=(8, 0))
        self.logs_button = ttk.Button(top, text="View Logs", command=self.view_logs)
        self.logs_button.pack(side="left", padx=(8, 0))

        self.admin_label = ttk.Label(top, text="", foreground="#555")
        self.admin_label.pack(side="right")

        layers = ttk.LabelFrame(top, text="Layers")
        layers.pack(side="right", padx=(16, 0))
        for index, layer in enumerate(LAYER_ORDER):
            var = tk.BooleanVar(value=True)
            self._layer_vars[layer.value] = var
            row, column = divmod(index, 4)
            ttk.Checkbutton(
                layers, text=LAYER_LABELS.get(layer, layer.value), variable=var
            ).grid(row=row, column=column, sticky="w", padx=(0, 10))

        self.status_label = ttk.Label(self.root, text="Click 'Run diagnosis' to start.", anchor="w")
        self.status_label.pack(fill="x", padx=8, pady=4)

        panes = ttk.PanedWindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=4)

        list_frame = ttk.Frame(panes)
        self.tree = ttk.Treeview(
            list_frame,
            columns=("status", "id", "layer", "title"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("status", text="Status")
        self.tree.heading("id", text="Check")
        self.tree.heading("layer", text="Layer")
        self.tree.heading("title", text="Finding")
        self.tree.column("status", width=70, anchor="center")
        self.tree.column("id", width=120)
        self.tree.column("layer", width=110)
        self.tree.column("title", width=360)
        self.tree.tag_configure("fail", foreground="#b00020")
        self.tree.tag_configure("warn", foreground="#8a6d00")
        self.tree.tag_configure("error", foreground="#b00020")
        self.tree.tag_configure("skip", foreground="#666666")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        panes.add(list_frame, weight=1)

        detail = ttk.Frame(panes)
        self.detail_text = tk.Text(detail, wrap="word", state="disabled")
        detail_scroll = ttk.Scrollbar(detail, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.pack(side="top", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        self.fix_frame = ttk.Frame(detail)
        self.fix_frame.pack(side="bottom", fill="x")
        panes.add(detail, weight=2)

        self.causes = LikelyCausesPanel(self.root)
        self.causes.pack(fill="x", padx=8, pady=(4, 8))

    def _refresh_admin_label(self) -> None:
        elevated = bool(self.runtime.admin_check())
        self.admin_label.configure(
            text=("Administrator" if elevated else "Standard user"),
            foreground=("#0a6b2d" if elevated else "#555"),
        )

    # -- threading plumbing ----------------------------------------------------

    def _poll_queue(self) -> None:
        self.bridge.poll()
        while True:
            try:
                message = self._queue.get_nowait()
            except queue.Empty:
                break
            kind = message.get("kind")
            if kind == "check":
                self.status_label.configure(
                    text=f"{message.get('status', '')}  {message.get('id', '')} - {message.get('title', '')}"
                )
            elif kind == "report":
                self._set_busy(False)
                self._populate(message["report"])
            elif kind == "diag_error":
                self._set_busy(False)
                text = f"Diagnosis failed: {message.get('error', '')}"
                self.status_label.configure(text=text)
                if not self.auto_confirm:
                    messagebox.showerror("NetScope", text)
            elif kind == "fix_outcome":
                self._set_busy(False)
                self._on_fix_outcome(message)
            elif kind == "fix_error":
                self._set_busy(False)
                text = f"Fix failed: {message.get('error', '')}"
                self.status_label.configure(text=text)
                if not self.auto_confirm:
                    messagebox.showerror("NetScope", text)
            elif kind == "fix_declined":
                self._set_busy(False)
                self.status_label.configure(text="Fix was cancelled.")
            elif kind == "report_exported":
                self._set_busy(False)
                path = message.get("path", "")
                self.status_label.configure(text=f"Report written to {path}")
                if not self.auto_confirm and messagebox.askyesno(
                    "NetScope", f"Report written to:\n{path}\n\nOpen the folder?"
                ):
                    self._open_path(os.path.dirname(path))
        self._poll_after = self.root.after(100, self._poll_queue)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.run_button.configure(state=state)
        self.export_button.configure(state=state)

    def _spawn(self, target: Any) -> None:
        thread = threading.Thread(target=target, daemon=True)
        thread.start()

    # -- diagnosis -------------------------------------------------------------

    def selected_layers(self) -> list[str]:
        selected = [name for name, var in self._layer_vars.items() if var.get()]
        return selected or [layer.value for layer in LAYER_ORDER]

    def start_diagnosis(self) -> None:
        if self._busy:
            return
        self.runtime.logger.action("gui", "diagnose", layers=self.selected_layers())
        self._set_busy(True)
        self.status_label.configure(text="Collecting network state...")
        self.tree.delete(*self.tree.get_children())
        self.causes.clear()
        self._show_detail(None)
        layers = self.selected_layers()
        self._spawn(lambda: self.worker_diagnose(layers))

    def worker_diagnose(self, layers: list[str]) -> None:
        """Runs on a worker thread; posts progress and the final report."""

        try:
            snapshot = self.runtime.engine.collect_snapshot()
            self._last_snapshot = snapshot
            report = self.runtime.engine.diagnose(
                layers=layers,
                snapshot=snapshot,
                mode="gui",
                on_check=lambda result: self._queue.put(
                    {
                        "kind": "check",
                        "id": result.id,
                        "status": _STATUS_LABELS.get(result.status, str(result.status)),
                        "title": result.title,
                    }
                ),
            )
        except KeyboardInterrupt:
            self.runtime.logger.event("interrupted", phase="gui-diagnose")
            self._queue.put({"kind": "diag_error", "error": "interrupted"})
            return
        except Exception as exc:
            self.runtime.logger.error("gui_diagnose_failed", exc_info=True, error=str(exc))
            self._queue.put({"kind": "diag_error", "error": str(exc)})
            return
        self._queue.put({"kind": "report", "report": report})

    def _populate(self, report: DiagnosticReport) -> None:
        self.report = report
        self.tree.delete(*self.tree.get_children())
        for index, result in enumerate(report.results):
            tag = result.status.value.lower()
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                tags=(tag,),
                values=(
                    _STATUS_LABELS.get(result.status, str(result.status)),
                    result.id,
                    LAYER_LABELS.get(result.layer, result.layer.value),
                    result.title,
                ),
            )
        first_failing = report.first_failing_layer
        summary = (
            f"Overall: {report.overall_status.value.upper()}   "
            f"exit code {report.exit_code}"
            + (f"   first failing layer: {LAYER_LABELS.get(first_failing, first_failing.value)}" if first_failing else "")
        )
        self.status_label.configure(text=summary)
        if report.results:
            self.tree.selection_set("0")
            self.tree.focus("0")

    def _on_select(self, _event: Any = None) -> None:
        selection = self.tree.selection()
        if not selection or self.report is None:
            self._show_detail(None)
            return
        try:
            result = self.report.results[int(selection[0])]
        except (IndexError, ValueError):
            self._show_detail(None)
            return
        self._show_detail(result)

    # -- detail rendering ------------------------------------------------------

    def _show_detail(self, result: CheckResult | None) -> None:
        self._selected = result
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        for widget in self.fix_frame.winfo_children():
            widget.destroy()
        if result is not None:
            lines = [
                f"{_STATUS_LABELS.get(result.status, str(result.status))}  {result.id} - {result.title}",
                "",
                result.message or "",
                "",
            ]
            if result.cause:
                lines.append(f"Likely cause: {result.cause}")
                lines.append("")
            if result.evidence:
                lines.append("Evidence:")
                payload = json.dumps(result.evidence, indent=2, sort_keys=True, default=str)
                lines.extend("  " + line for line in payload.splitlines())
                lines.append("")
            suggested = [fix_id for fix_id in result.fix_ids if self.catalog.get(fix_id) is not None]
            if suggested:
                lines.append("Suggested fixes:")
            self.detail_text.insert("end", "\n".join(lines))
            for fix_id in suggested:
                entry = self.catalog.get(fix_id)
                if entry is None:
                    continue
                label = (
                    f"Explain {fix_id} - {entry.name} (cannot be fixed from this PC)"
                    if entry.detection_only
                    else f"Proceed to Fix {fix_id} - {entry.name}"
                )
                button = ttk.Button(
                    self.fix_frame,
                    text=label,
                    command=lambda fix_id=fix_id: self.proceed_to_fix(fix_id),
                )
                button.pack(fill="x", pady=1)
        self.detail_text.configure(state="disabled")

    # -- fix flow --------------------------------------------------------------

    def proceed_to_fix(self, fix_id: str) -> None:
        if self._busy:
            return
        entry = self.catalog.get(fix_id)
        if entry is None:
            self.status_label.configure(text=f"Unknown fix id: {fix_id}")
            return
        self.runtime.logger.action("gui", "proceed_to_fix", fix_id=fix_id)
        result = self._selected
        if entry.detection_only:
            reason = "This finding cannot be fixed from this PC; no setting on this device will change it."
            section = unresolved_section(
                entry,
                evidence=result.evidence if result is not None else None,
                another_device_works=self.bridge.answer_directly("isolation"),
                reason=reason,
            )
            section["finding_id"] = result.id if result is not None else entry.id
            section["finding_title"] = result.title if result is not None else entry.name
            self.causes.show(section)
            self.status_label.configure(text=f"{fix_id} is DETECT-ONLY; see the likely causes below.")
            self.runtime.logger.unresolved(entry.id, causes=section)
            return
        self._set_busy(True)
        self.status_label.configure(text=f"Preparing fix {fix_id}...")
        self._spawn(lambda: self.worker_fix(entry, result))

    def worker_fix(self, entry: FixEntry, result: CheckResult | None) -> None:
        """Runs on a worker thread; dialogs come back through the bridge."""

        executor = self.runtime.executor()
        try:
            plan = executor.prepare(entry, snapshot=self._last_snapshot)
        except (PlanError, CatalogError) as exc:
            self._queue.put({"kind": "fix_error", "fix_id": entry.id, "error": str(exc)})
            return
        if not self.bridge.submit("fix_confirm", {"plan": plan, "entry_id": entry.id}):
            self._queue.put({"kind": "fix_declined", "fix_id": entry.id})
            return
        try:
            outcome = executor.run(
                entry,
                plan=plan,
                assume_yes=True,
                risk_ack=False,
                confirm=lambda prompt: bool(self.bridge.submit("confirm", prompt)),
                isolation=lambda: self.bridge.submit("isolation"),
            )
        except KeyboardInterrupt:
            self.runtime.logger.event("interrupted", phase="gui-fix")
            self._queue.put({"kind": "fix_error", "fix_id": entry.id, "error": "interrupted"})
            return
        except Exception as exc:
            self.runtime.logger.error("gui_fix_failed", exc_info=True, fix_id=entry.id, error=str(exc))
            self._queue.put({"kind": "fix_error", "fix_id": entry.id, "error": str(exc)})
            return
        self._queue.put({"kind": "fix_outcome", "outcome": outcome, "entry": entry})

    def _on_fix_outcome(self, message: dict[str, Any]) -> None:
        outcome: FixOutcome = message["outcome"]
        entry: FixEntry = message["entry"]
        lines = render_fix_outcome(outcome.to_dict())
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("end", "\n".join(lines))
        self.detail_text.configure(state="disabled")
        for widget in self.fix_frame.winfo_children():
            widget.destroy()
        if outcome.rollback_available:
            undo = ttk.Button(
                self.fix_frame,
                text=f"Undo {entry.id} (rollback)",
                command=lambda entry=entry: self.rollback_fix(entry),
            )
            undo.pack(fill="x", pady=1)
        if outcome.status == "needs_admin":
            guidance = admin_guidance([*gui_relaunch_argv()])
            if messagebox.askyesno(
                "Administrator needed",
                guidance + "\n\nRelaunch NetScope as administrator now?",
            ):
                relaunch_elevated([*gui_relaunch_argv()])
                self.shutdown()
                return
        if outcome.unresolved:
            self.causes.show(outcome.unresolved)
        self.status_label.configure(text=f"Fix {entry.id}: {outcome.status.replace('_', ' ')}")

    def rollback_fix(self, entry: FixEntry) -> None:
        if self._busy:
            return
        self.runtime.logger.action("gui", "rollback", fix_id=entry.id)
        self._set_busy(True)
        self.status_label.configure(text=f"Rolling back {entry.id}...")
        self._spawn(lambda: self.worker_rollback(entry))

    def worker_rollback(self, entry: FixEntry) -> None:
        executor = self.runtime.executor()
        try:
            outcome = executor.rollback(
                entry,
                confirm=lambda prompt: bool(self.bridge.submit("confirm", prompt)),
            )
        except Exception as exc:
            self.runtime.logger.error("gui_rollback_failed", exc_info=True, fix_id=entry.id, error=str(exc))
            self._queue.put({"kind": "fix_error", "fix_id": entry.id, "error": str(exc)})
            return
        self._queue.put({"kind": "fix_outcome", "outcome": outcome, "entry": entry})

    # -- dialogs (UI thread) ---------------------------------------------------

    def _handle_dialog(self, kind: str, payload: Any) -> Any:
        if kind == "fix_confirm":
            return self._dialog_fix_confirm(payload["plan"])
        if kind == "confirm":
            return self._dialog_confirm(str(payload))
        if kind == "isolation":
            return self._dialog_isolation()
        return None

    def _dialog_fix_confirm(self, plan: Any) -> bool:
        if self.auto_confirm:
            return True
        entry = plan.entry
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Proceed to fix {entry.id}?")
        dialog.transient(self.root)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        labels = ttk.Label(
            body,
            text=(
                f"Admin: {'yes' if entry.admin else 'no'}   "
                f"Risk: {entry.risk.upper()}   "
                f"Reboot: {'yes' if entry.reboot else 'no'}"
            )
            + "   "
            + ("DETECT-ONLY" if entry.detection_only else ""),
        )
        labels.pack(anchor="w")
        text = tk.Text(body, wrap="word", width=90, height=22)
        for line in plan.preview_lines:
            text.insert("end", line + "\n")
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, pady=6)
        answer: dict[str, bool] = {}

        def close(value: bool) -> None:
            answer["proceed"] = value
            dialog.destroy()

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Proceed to Fix", command=lambda: close(True)).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=lambda: close(False)).pack(side="right", padx=6)
        dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))
        dialog.grab_set()
        self.root.wait_window(dialog)
        return bool(answer.get("proceed"))

    def _dialog_confirm(self, prompt: str) -> bool:
        if self.auto_confirm:
            return True
        if prompt.startswith("This step is HIGH RISK"):
            return bool(
                messagebox.askyesno(
                    "HIGH RISK step",
                    prompt
                    + "\n\nThis step can break connectivity (for example VPN routes or "
                    "firewall rules). Continue only if you understand the risk.",
                    icon="warning",
                )
            )
        if prompt.startswith("Roll back"):
            return bool(messagebox.askyesno("Undo fix", prompt))
        return bool(messagebox.askyesno("Confirm fix step", prompt))

    def _dialog_isolation(self) -> bool | None:
        if self.auto_confirm:
            return None
        dialog = tk.Toplevel(self.root)
        dialog.title("Isolation question")
        dialog.transient(self.root)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Does another device on the same network work?", wraplength=380).pack(pady=6)
        answer: dict[str, Any] = {}

        def close(value: Any) -> None:
            answer["value"] = value
            dialog.destroy()

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Yes", command=lambda: close(True)).pack(side="left", padx=6)
        ttk.Button(buttons, text="No", command=lambda: close(False)).pack(side="left", padx=6)
        ttk.Button(buttons, text="Unknown", command=lambda: close(None)).pack(side="left", padx=6)
        dialog.protocol("WM_DELETE_WINDOW", lambda: close(None))
        dialog.grab_set()
        self.root.wait_window(dialog)
        return answer.get("value")

    # -- logs and report -------------------------------------------------------

    def view_logs(self) -> None:
        self.runtime.logger.action("gui", "view_logs")
        path = config.log_dir() / LOG_FILE_NAME
        if path.exists():
            self._open_path(str(path))
        else:
            messagebox.showinfo("NetScope", f"No log file yet:\n{path}")

    def export_report(self) -> None:
        if self._busy:
            return
        if self.auto_confirm:
            fmt = "txt"
        else:
            fmt = "txt" if messagebox.askyesno(
                "Report format", "Export the report as text?\n\n(No = JSON)", icon="question"
            ) else "json"
        self.runtime.logger.action("gui", "export_report", report_format=fmt)
        self._set_busy(True)
        self.status_label.configure(text="Building report...")
        self._spawn(lambda: self.worker_report(fmt))

    def worker_report(self, report_format: str) -> None:
        try:
            snapshot = self.runtime.engine.collect_snapshot()
            report = self.runtime.engine.diagnose(snapshot=snapshot, mode="report")
            info = build_info(snapshot)
        except Exception as exc:
            self.runtime.logger.error("gui_report_failed", exc_info=True, error=str(exc))
            self._queue.put({"kind": "diag_error", "error": str(exc)})
            return
        unresolved: list[dict[str, Any]] = []
        try:
            unresolved = build_unresolved_sections(report, self.catalog)
        except CatalogError:
            pass
        payload = {
            "info": info,
            "diagnostic": report.to_dict(include_snapshot=False),
            "unresolved": unresolved,
        }
        if report_format == "json":
            content = json.dumps(payload, indent=2, sort_keys=True, default=str)
            extension = "json"
        else:
            content = render_report_text(payload)
            extension = "txt"
        directory = config.report_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = directory / f"netscope-report-{stamp}.{extension}"
        try:
            destination.write_text(content, encoding="utf-8")
        except OSError as exc:
            self._queue.put({"kind": "diag_error", "error": str(exc)})
            return
        self._queue.put({"kind": "report_exported", "path": str(destination)})

    def _open_path(self, path: str) -> bool:
        try:
            if os.name == "nt" and hasattr(os, "startfile"):
                os.startfile(path)  # type: ignore[attr-defined]
                return True
            return bool(webbrowser.open(Path(path).resolve().as_uri()))
        except Exception:
            return False

    # -- lifecycle -------------------------------------------------------------

    def shutdown(self) -> None:
        if self._poll_after is not None:
            try:
                self.root.after_cancel(self._poll_after)
            except Exception:
                pass
            self._poll_after = None
        try:
            self.runtime.logger.event("app_stop", mode="gui")
            flush_logging()
        finally:
            self.root.destroy()


def run_gui(runtime: GuiRuntime | None = None) -> int:
    """Create the window and run the Tk main loop."""

    runtime = runtime or build_runtime()
    root = tk.Tk()
    NetScopeGui(root, runtime)
    root.mainloop()
    return 0
