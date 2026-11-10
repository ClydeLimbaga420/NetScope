"""JSON API routes calling the existing engine/fixes/CLI utilities."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

import config
from cli.admin import is_admin, relaunch_elevated
from core.info import build_info
from core.logging_config import LOG_FILE_NAME
from fixes.executor import FixExecutor
from fixes.if_unresolved import unresolved_section
from gui.launch import gui_relaunch_argv
from web.jobs import Job

api_bp = Blueprint("api", __name__)


def _state():  # type: ignore[no-untyped-def]
    return current_app.extensions["netscope_state"]


def _err(code: str, message: str, status: int = 400):  # type: ignore[no-untyped-def]
    return jsonify({"error": {"code": code, "message": message}}), status


def _json_body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


@api_bp.get("/status")
def api_status():  # type: ignore[no-untyped-def]
    st = _state()
    rt = st.runtime
    return jsonify(
        {
            "app": config.APP_NAME,
            "version": config.APP_VERSION,
            "admin": bool(is_admin()),
            "session_id": st.session_id,
            "dry_run_default": False,
            "powershell": {
                "available": getattr(getattr(rt, "ps", None), "available", None),
                "constrained_language": getattr(getattr(rt, "ps", None), "constrained_language", None),
            },
        }
    )


@api_bp.post("/heartbeat")
def api_heartbeat():  # type: ignore[no-untyped-def]
    st = _state()
    st.touch()
    return jsonify({"ok": True, "ts": time.time()})


@api_bp.post("/shutdown")
def api_shutdown():  # type: ignore[no-untyped-def]
    st = _state()
    st.logger.event("shutdown_requested", source="web")
    st.shutdown_event.set()
    return jsonify({"ok": True})


@api_bp.post("/diagnose")
def api_diagnose():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    layers = body.get("layers")
    if layers is not None and not isinstance(layers, list):
        return _err("invalid_layers", "layers must be a list", 400)
    job = st.jobs.create("diagnose", meta={"layers": layers})
    runtime = st.runtime

    def work(job_obj: Job):  # type: ignore[no-untyped-def]
        st.logger.action("web", "diagnose_start", layers=layers)
        snapshot = runtime.engine.collect_snapshot()
        st.last_snapshot = snapshot

        def on_check(result):  # type: ignore[no-untyped-def]
            job_obj.events.put({"type": "check", "result": result.to_dict()})

        report = runtime.engine.diagnose(
            layers=layers, snapshot=snapshot, on_check=on_check, mode="web"
        )
        st.last_report = report
        st.logger.action("web", "diagnose_complete", overall_status=report.overall_status.value)
        return report.to_dict(include_snapshot=False)

    st.jobs.submit(job, work)
    return jsonify({"job_id": job.id})


@api_bp.get("/jobs/<job_id>")
def api_job(job_id: str):  # type: ignore[no-untyped-def]
    st = _state()
    job = st.jobs.get(job_id)
    if not job:
        return _err("not_found", "Job not found.", 404)
    return jsonify(job.to_dict())


@api_bp.get("/jobs/<job_id>/events")
def api_job_events(job_id: str):  # type: ignore[no-untyped-def]
    st = _state()
    job = st.jobs.get(job_id)
    if not job:
        return _err("not_found", "Job not found.", 404)
    return st.jobs.stream(job)


@api_bp.post("/jobs/<job_id>/cancel")
def api_job_cancel(job_id: str):  # type: ignore[no-untyped-def]
    st = _state()
    ok = st.jobs.cancel(job_id)
    if not ok:
        return _err("not_found", "Job not found.", 404)
    st.logger.action("web", "job_cancel", job_id=job_id)
    return jsonify({"ok": True})


@api_bp.get("/findings")
def api_findings():  # type: ignore[no-untyped-def]
    st = _state()
    report = st.last_report
    if not report:
        return jsonify({"report": None, "findings": []})
    findings = [r.to_dict() for r in report.results if getattr(r.status, "value", str(r.status)) in {"fail", "warn", "error"}]
    return jsonify({"report": report.to_dict(include_snapshot=False), "findings": findings})


@api_bp.get("/info")
def api_info():  # type: ignore[no-untyped-def]
    st = _state()
    snap = st.last_snapshot
    if snap is None:
        try:
            snap = st.runtime.engine.collect_snapshot()
            st.last_snapshot = snap
        except Exception as exc:  # noqa: BLE001
            return _err("info_failed", str(exc), 500)
    info = build_info(snap)
    info["admin"] = bool(is_admin())
    return jsonify(info)


@api_bp.get("/logs")
def api_logs():  # type: ignore[no-untyped-def]
    tail = request.args.get("tail", default="200")
    try:
        tail_n = max(1, min(5000, int(tail)))
    except Exception:
        tail_n = 200
    level = (request.args.get("level") or "").upper()
    session = request.args.get("session") or ""
    q = (request.args.get("q") or "").lower()
    log_path = config.log_dir() / LOG_FILE_NAME
    if not log_path.exists():
        return jsonify({"path": str(log_path), "entries": []})
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:  # noqa: BLE001
        return _err("log_read_failed", str(exc), 500)
    entries = []
    for line in lines[-tail_n:]:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if level and str(obj.get("level", "")).upper() != level:
            continue
        if session and str(obj.get("session_id", "")) != session:
            continue
        if q and q not in line.lower():
            continue
        entries.append(obj)
    return jsonify({"path": str(log_path), "entries": entries})


@api_bp.post("/ui-event")
def api_ui_event():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    action = str(body.get("action") or "ui_event")
    st.logger.action("web", action, **{k: v for k, v in body.items() if k != "action"})
    return jsonify({"ok": True})


@api_bp.post("/open-log-folder")
def api_open_log_folder():  # type: ignore[no-untyped-def]
    path = str(config.log_dir())
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return _err("open_failed", str(exc), 500)
    _state().logger.action("web", "open_log_folder", path=path)
    return jsonify({"ok": True, "path": path})


@api_bp.post("/elevate")
def api_elevate():  # type: ignore[no-untyped-def]
    st = _state()
    try:
        relaunch_elevated(gui_relaunch_argv())  # may relaunch GUI-mode process
        st.logger.action("web", "elevate_requested")
    except Exception as exc:  # noqa: BLE001
        st.logger.error("elevate_failed", source="web", error=str(exc))
        return _err("elevate_failed", str(exc), 500)
    st.shutdown_event.set()
    return jsonify({"ok": True})


# --- fix plan/execute/rollback: minimal safe skeleton (to be completed) ---

_FIX_PLANS: dict[str, dict[str, Any]] = {}


@api_bp.post("/fix/plan")
def api_fix_plan():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    fix_id = str(body.get("fix_id") or "")
    if not fix_id:
        return _err("missing_fix_id", "fix_id is required", 400)
    try:
        entry = st.runtime.catalog.require(fix_id)
    except Exception:
        return _err("unknown_fix_id", f"Unknown fix id: {fix_id}", 404)
    snap = st.last_snapshot or st.runtime.engine.collect_snapshot()
    st.last_snapshot = snap
    executor = st.runtime.executor()
    try:
        plan = executor.prepare(entry, snapshot=snap, overrides=body.get("params") or {})
    except Exception as exc:  # noqa: BLE001
        return _err("plan_failed", str(exc), 400)
    token = uuid.uuid4().hex + secrets_token()
    expires = time.time() + 300
    record = {
        "token": token,
        "expires": expires,
        "fix_id": fix_id,
        "plan": plan,
        "entry": entry,
        "dry_run": bool(body.get("dry_run", False)),
        "used": False,
    }
    _FIX_PLANS[token] = record
    st.logger.action("web", "fix_plan", fix_id=fix_id)
    return jsonify(
        {
            "fix_id": fix_id,
            "confirmation_token": token,
            "expires_at": expires,
            "preview": plan.preview_lines,
            "admin": entry.admin,
            "risk": entry.risk,
            "reboot": entry.reboot,
            "rollback": entry.rollback,
            "snapshot": entry.snapshot,
            "dry_run": bool(body.get("dry_run", False)),
            "name": entry.name,
            "explanation": entry.explanation,
        }
    )


def secrets_token() -> str:
    import secrets
    return secrets.token_urlsafe(16)


@api_bp.post("/fix/execute")
def api_fix_execute():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    token = str(body.get("confirmation_token") or "")
    record = _FIX_PLANS.get(token)
    if not record or record.get("used"):
        return _err("invalid_token", "Invalid or used confirmation token.", 403)
    if time.time() > float(record.get("expires", 0)):
        return _err("expired_token", "Confirmation token expired.", 403)
    entry = record["entry"]
    plan = record["plan"]
    if str(getattr(entry, "risk", "")).lower() == "high" and not body.get("second_confirmation"):
        st.logger.event("security_rejected", source="web", reason="risk_h_second_confirmation_missing", fix_id=entry.id)
        return _err("second_confirmation_required", "High-risk fix requires second confirmation.", 403)
    if not st.jobs.can_start_fix():
        return _err("fix_in_progress", "Another fix is already running.", 409)
    dry_run = bool(body.get("dry_run", record.get("dry_run", False)))
    record["used"] = True
    job = st.jobs.create("fix", meta={"fix_id": entry.id, "dry_run": dry_run})
    st.jobs.mark_fix_started(job.id)

    def work(job_obj: Job):  # type: ignore[no-untyped-def]
        st.logger.action("web", "fix_execute", fix_id=entry.id, dry_run=dry_run)
        executor = st.runtime.executor()
        outcome = executor.run(
            entry,
            plan=plan,
            assume_yes=True,
            dry_run=dry_run,
            confirm=lambda _q: True,  # server-side token is the confirmation
            isolation=lambda: body.get("another_device_works"),
        )
        st.logger.action("web", "fix_outcome", fix_id=entry.id, status=outcome.status)
        return outcome.to_dict()

    try:
        st.jobs.submit(job, work)
    finally:
        # mark finished handled by polling? simpler: wrap not easy; worker will end status
        pass
    # ensure active cleared when done via monitor thread not implemented; lightweight approach:
    def _clear():  # type: ignore[no-untyped-def]
        while job.status in {"queued", "running"}:
            time.sleep(0.2)
        st.jobs.mark_fix_finished(job.id)
    import threading as _th
    _th.Thread(target=_clear, daemon=True).start()
    return jsonify({"job_id": job.id, "fix_id": entry.id})


@api_bp.post("/unresolved/answer")
def api_unresolved_answer():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    ans = body.get("another_device_works")
    if ans in ("yes", True):
        val = True
    elif ans in ("no", False):
        val = False
    else:
        val = None
    fix_id = body.get("fix_id")
    report = st.last_report
    # best-effort: if fix_id provided, find entry; else return generic note
    result = {"another_device_works": val, "sections": []}
    if fix_id:
        try:
            entry = st.runtime.catalog.require(str(fix_id))
            section = unresolved_section(entry, another_device_works=val)
            result["sections"] = [section]
        except Exception:
            pass
    st.logger.action("web", "unresolved_answer", answer=ans, fix_id=fix_id)
    return jsonify(result)
