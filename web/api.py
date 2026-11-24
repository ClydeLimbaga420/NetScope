"""JSON API routes calling the existing engine/fixes/CLI utilities."""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

import config
from cli.admin import is_admin, relaunch_elevated
from cli.render import render_report_text
from cli.utilities import UtilityRunner
from core.info import build_info
from core.logging_config import LOG_FILE_NAME, clear_logs
from fixes.catalog import CatalogError, load_catalog
from fixes.executor import FixExecutor
from fixes.gateway_config import auto_configure_gateway
from fixes.if_unresolved import build_unresolved_sections, unresolved_section
from cli.launch import gui_relaunch_argv
from core.checks.descriptors import CHECK_DESCRIPTORS
from core.models import Layer

api_bp = Blueprint("api", __name__)

# Snapshot collection spawns a burst of child processes. Serialising it and
# reusing the monitoring service's cached snapshot keeps a single UI open from
# triggering several full collections at the same time.
_SNAPSHOT_LOCK = threading.Lock()


def _state():  # type: ignore[no-untyped-def]
    return current_app.extensions["netscope_state"]


def _shared_snapshot(st, *, fresh=False):  # type: ignore[no-untyped-def]
    if not fresh:
        snap = getattr(st, "last_snapshot", None)
        if snap is not None:
            return snap
    with _SNAPSHOT_LOCK:
        snap = None
        if not fresh:
            snap = getattr(st, "last_snapshot", None)
            if snap is not None:
                return snap
            monitoring = getattr(getattr(st, "runtime", None), "monitoring", None)
            getter = getattr(monitoring, "get_snapshot", None)
            if callable(getter):
                try:
                    snap = getter()
                except Exception:  # noqa: BLE001 - fall back to a direct collection
                    snap = None
        if snap is None:
            snap = st.runtime.engine.collect_snapshot()
        st.last_snapshot = snap
        return snap


def _err(code: str, message: str, status: int = 400):  # type: ignore[no-untyped-def]
    return jsonify({"error": {"code": code, "message": message}}), status


def _json_body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


def _monitoring_failure(st, event: str, code: str, message: str):  # type: ignore[no-untyped-def]
    st.logger.error(event, source="web", error=message)
    return _err(code, message, 500)


@api_bp.get("/status")
def api_status():  # type: ignore[no-untyped-def]
    st = _state()
    try:
        payload = st.runtime.monitoring.get_status()
    except Exception as exc:  # noqa: BLE001
        return _monitoring_failure(
            st,
            "monitoring_status_failed",
            "status_failed",
            str(exc) or "Status collection failed.",
        )
    payload.update(
        {
            "app": config.APP_NAME,
            "version": config.APP_VERSION,
            "admin": bool(is_admin()),
            "session_id": st.session_id,
            "dry_run_default": False,
            "powershell": {
                "available": True if getattr(st.runtime, "ps", None) is not None else None
            },
        }
    )
    return jsonify(payload)


@api_bp.get("/checks")
def api_checks():  # type: ignore[no-untyped-def]
    return jsonify({"checks": [d.to_dict() for d in CHECK_DESCRIPTORS]})


@api_bp.post("/heartbeat")
def api_heartbeat():  # type: ignore[no-untyped-def]
    st = _state()
    st.touch()
    return jsonify({"ok": True, "ts": time.time()})


@api_bp.post("/shutdown")
def api_shutdown():  # type: ignore[no-untyped-def]
    st = _state()
    st.logger.action("web", "shutdown")
    st.logger.event("shutdown_requested", source="web")
    st.shutdown_event.set()
    return jsonify({"ok": True})


@api_bp.post("/diagnose")
def api_diagnose():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    layers = body.get("layers")
    if layers is not None and (not isinstance(layers, list) or not all(isinstance(x, str) for x in layers)):
        return _err("invalid_layers", "layers must be a list of layer names", 400)
    checks = body.get("checks")
    if checks is not None and (not isinstance(checks, list) or not all(isinstance(x, str) for x in checks)):
        return _err("invalid_checks", "checks must be a list of check ids", 400)
    job = st.jobs.create("diagnose", meta={"layers": layers, "checks": checks})
    runtime = st.runtime

    def work(job_obj):  # type: ignore[no-untyped-def]
        st.logger.action("web", "diagnose_start", layers=layers, checks=checks)
        snap = _shared_snapshot(st, fresh=True)

        def on_check(result):  # type: ignore[no-untyped-def]
            job_obj.events.put({"type": "check", "result": result.to_dict()})

        report = runtime.engine.diagnose(
            layers=layers, snapshot=snap, on_check=on_check, mode="web", check_ids=checks
        )
        st.last_report = report
        st.logger.action("web", "diagnose_complete", overall_status=report.overall_status.value, exit_code=report.exit_code)
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
    findings = [
        r.to_dict()
        for r in report.results
        if getattr(r.status, "value", str(r.status)) in {"fail", "warn", "error"}
    ]
    return jsonify({"report": report.to_dict(include_snapshot=False), "findings": findings})


@api_bp.get("/fixes")
def api_fixes():  # type: ignore[no-untyped-def]
    st = _state()
    entries = getattr(st.runtime.catalog, "entries", ())
    fixes = [
        {
            "id": entry.id,
            "name": entry.name,
            "symptom": entry.symptom,
            "explanation": entry.explanation,
            "admin": entry.admin,
            "risk": entry.risk,
            "reboot": entry.reboot,
            "detection_only": entry.detection_only,
        }
        for entry in entries
    ]
    fixes.sort(key=lambda item: item["id"])
    return jsonify({"fixes": fixes})


@api_bp.get("/fixes/<fix_id>")
def api_fix_detail(fix_id: str):  # type: ignore[no-untyped-def]
    st = _state()
    catalog = getattr(st.runtime, "catalog", None)
    entry = catalog.get(fix_id) if catalog is not None else None
    if entry is None:
        return _err("unknown_fix", f"Unknown fix id: {fix_id}", 404)
    return jsonify({"fix": entry.to_dict(), "admin": bool(is_admin())})


@api_bp.get("/info")
def api_info():  # type: ignore[no-untyped-def]
    st = _state()
    try:
        snap = _shared_snapshot(st)
    except Exception as exc:  # noqa: BLE001
        st.logger.error("web_info_failed", source="web", error=str(exc), exc_info=True)
        return _err("info_failed", str(exc), 500)
    info = build_info(snap)
    info["admin"] = bool(is_admin())
    return jsonify(info)


@api_bp.post("/tools/<name>")
def api_tools(name: str):  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    allowed = {"ping", "trace", "dns", "arp", "routes", "ports", "mtu", "speedtest"}
    if name not in allowed:
        return _err("unknown_tool", f"Unknown tool: {name}", 404)
    job = st.jobs.create("tool", meta={"tool": name, "params": body})
    from cli.context import CliContext
    from cli.colors import Colorizer
    import io
    ctx = CliContext(
        logger=st.runtime.logger,
        runner=st.runtime.runner,
        ps=st.runtime.ps,
        probe=getattr(st.runtime.engine, "probe", None),
        color=Colorizer(False),
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    util = UtilityRunner(ctx)

    def work(_job):  # type: ignore[no-untyped-def]
        st.logger.action("web", "tool_start", tool=name)
        try:
            if name == "ping":
                res = util.ping(str(body.get("host", "")), int(body.get("count", 4)), float(body.get("timeout", 1.0)))
            elif name == "trace":
                res = util.trace(str(body.get("host", "")), int(body.get("max_hops", 30)), float(body.get("timeout", 60.0)))
            elif name == "dns":
                res = util.dns(str(body.get("name", body.get("host", ""))), body.get("server"))
            elif name == "arp":
                res = util.arp()
            elif name == "routes":
                res = util.routes()
            elif name == "ports":
                res = util.ports(str(body.get("host", "")), str(body.get("ports", "")), float(body.get("timeout", 1.0)))
            elif name == "mtu":
                res = util.mtu(str(body.get("host", "")), float(body.get("timeout", 1.5)))
            elif name == "speedtest":
                res = util.speed_test()
            else:
                raise ValueError("unknown tool")
        except Exception as exc:  # noqa: BLE001
            st.logger.error("tool_failed", source="web", tool=name, error=str(exc), exc_info=True)
            raise
        st.logger.action("web", "tool_complete", tool=name)
        return res

    st.jobs.submit(job, work)
    return jsonify({"job_id": job.id})


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
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = deque(handle, maxlen=tail_n)
    except Exception as exc:  # noqa: BLE001
        return _err("log_read_failed", str(exc), 500)
    entries = []
    for line in lines:
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


@api_bp.get("/logs/stream")
def api_logs_stream():  # type: ignore[no-untyped-def]
    st = _state()
    log_path = config.log_dir() / LOG_FILE_NAME

    def generate():  # type: ignore[no-untyped-def]
        yield ": ok\n\n"
        try:
            pos = log_path.stat().st_size if log_path.exists() else 0
        except Exception:
            pos = 0
        while not st.shutdown_event.is_set():
            produced = False
            try:
                if log_path.exists():
                    with log_path.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for line in chunk.splitlines():
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        produced = True
                        yield f"data: {json.dumps({'type':'log','entry':obj}, default=str)}\n\n"
            except Exception:
                pass
            if not produced:
                yield ": keep-alive\n\n"
            time.sleep(1)

    resp = Response(stream_with_context(generate()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@api_bp.get("/report")
def api_report():  # type: ignore[no-untyped-def]
    st = _state()
    fmt = (request.args.get("format") or "json").lower()
    if fmt not in {"json", "txt"}:
        return _err("invalid_format", "format must be json or txt", 400)
    report = st.last_report
    snap = st.last_snapshot
    if report is None or snap is None:
        try:
            snap = _shared_snapshot(st)
            report = st.runtime.engine.diagnose(snapshot=snap, mode="report")
            st.last_report = report
        except Exception as exc:  # noqa: BLE001
            st.logger.error("report_failed", source="web", error=str(exc), exc_info=True)
            return _err("report_failed", str(exc), 500)
    info = build_info(snap)
    unresolved = []
    try:
        unresolved = build_unresolved_sections(report, load_catalog())
    except CatalogError as exc:
        st.logger.warning("fix_catalog_unavailable", source="web", error=str(exc))
    payload = {"info": info, "diagnostic": report.to_dict(include_snapshot=False), "unresolved": unresolved}
    if fmt == "json":
        return jsonify(payload)
    text = render_report_text(payload)
    return Response(text, mimetype="text/plain; charset=utf-8")


@api_bp.post("/ui-event")
def api_ui_event():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    action = str(body.get("action") or "ui_event")
    fields = {k: v for k, v in body.items() if k != "action"}
    st.logger.action("web", action, **fields)
    return jsonify({"ok": True})


@api_bp.post("/open-log-folder")
def api_open_log_folder():  # type: ignore[no-untyped-def]
    path = str(config.log_dir())
    try:
        if os.name == "nt" and hasattr(os, "startfile"):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            import webbrowser
            webbrowser.open(Path(path).resolve().as_uri())
    except Exception as exc:  # noqa: BLE001
        return _err("open_failed", str(exc), 500)
    _state().logger.action("web", "open_log_folder", path=path)
    return jsonify({"ok": True, "path": path})


@api_bp.post("/elevate")
def api_elevate():  # type: ignore[no-untyped-def]
    st = _state()
    argv = gui_relaunch_argv(no_browser=True, data_dir=str(config.data_dir()))
    handoff = getattr(st, "elevate_handoff", None)
    if handoff and handoff.get("active"):
        return _err("elevation_in_progress", "An administrator restart is already in progress.", 409)

    callback_token = secrets.token_urlsafe(32)
    callback_url = f"http://127.0.0.1:{int(st.port)}/__elevate_complete__"
    launch_argv = [
        *argv,
        "--handoff-url",
        callback_url,
        "--handoff-token",
        callback_token,
    ]
    st.logger.action(
        "web",
        "elevate_launch",
        argv=list(argv),
        current_admin=is_admin(),
        executable=sys.executable,
    )

    st.begin_elevate_handoff(callback_token)
    handle = getattr(st, "instance_lock_handle", None)
    released_lock = handle is not None
    try:
        from web.run import _release_instance_lock, _remove_lock

        if handle is not None:
            _remove_lock(os.getpid())
            st.instance_lock_handle = None
            _release_instance_lock(handle)
        launched = relaunch_elevated(launch_argv, windowless=True)
    except Exception as exc:  # noqa: BLE001
        st.elevate_handoff.update(active=False, error=str(exc))
        st.logger.error("elevate_failed", source="web", error=str(exc), exc_info=True)
        if released_lock:
            _restore_elevate_instance(st)
        return _err("elevate_failed", str(exc), 500)

    if not launched:
        st.elevate_handoff.update(
            active=False,
            error="Administrator elevation was cancelled or Windows could not start the elevated process.",
        )
        st.logger.action("web", "elevate_cancelled")
        if released_lock:
            _restore_elevate_instance(st)
        return _err("elevate_cancelled", st.elevate_handoff["error"], 409)

    # The administrator process logs to the same rotating file. Start its
    # session with an empty log instead of the standard user's history.
    clear_logs()
    st.logger.action("web", "elevate_requested")
    return jsonify({"ok": True, "handoff": True})


def _restore_elevate_instance(st: Any) -> None:
    try:
        from web.run import _restore_instance_lock

        if not _restore_instance_lock(st):
            st.logger.error(
                "elevate_handoff_lock_restore_failed",
                source="web",
                reason="instance lock is held by another process",
            )
    except Exception as exc:  # noqa: BLE001
        st.logger.error(
            "elevate_handoff_lock_restore_failed",
            source="web",
            error=str(exc),
            exc_info=True,
        )


@api_bp.get("/elevate/status")
def api_elevate_status():  # type: ignore[no-untyped-def]
    st = _state()
    handoff = getattr(st, "elevate_handoff", None)
    if not handoff:
        return jsonify({"status": "idle"})
    if handoff.get("url"):
        return jsonify({"status": "ready", "url": handoff["url"]})
    if handoff.get("error"):
        return jsonify({"status": "error", "message": handoff["error"]})
    if handoff.get("active"):
        return jsonify({"status": "pending"})
    return jsonify({"status": "idle"})


# --- fix plan/execute/rollback (server-side confirmation enforced) ---

_FIX_PLANS: dict[str, dict[str, Any]] = {}
_FIX_PLANS_LOCK = threading.Lock()
_PLAN_TTL = 300


def _secrets_token() -> str:
    import secrets
    return secrets.token_urlsafe(18)


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
    try:
        snap = _shared_snapshot(st)
    except Exception as exc:  # noqa: BLE001
        return _err("snapshot_failed", str(exc), 500)
    executor = st.runtime.executor()
    try:
        plan = executor.prepare(entry, snapshot=snap, overrides=body.get("params") or body.get("overrides") or {})
    except Exception as exc:  # noqa: BLE001
        return _err("plan_failed", str(exc), 400)
    token = _secrets_token()
    expires = time.time() + _PLAN_TTL
    record = {
        "token": token,
        "expires": expires,
        "fix_id": fix_id,
        "plan": plan,
        "entry": entry,
        "snapshot": snap,
        "used": False,
    }
    with _FIX_PLANS_LOCK:
        now = time.time()
        for expired_token in [
            key for key, value in _FIX_PLANS.items()
            if float(value.get("expires", 0)) < now
        ]:
            _FIX_PLANS.pop(expired_token, None)
        _FIX_PLANS[token] = record
    st.logger.action("web", "fix_plan_requested", fix_id=fix_id, risk=entry.risk, admin=entry.admin)
    return jsonify(
        {
            "fix_id": fix_id,
            "name": entry.name,
            "confirmation_token": token,
            "expires_at": expires,
            "preview": plan.preview_lines,
            "admin": entry.admin,
            "risk": entry.risk,
            "reboot": entry.reboot,
            "rollback": entry.rollback,
            "rollback_notes": entry.rollback_notes,
            "snapshot_plan": entry.snapshot,
            "explanation": entry.explanation,
            "detection_only": entry.detection_only,
        }
    )


@api_bp.post("/gateway/configure")
def api_gateway_configure():  # type: ignore[no-untyped-def]
    st = _state()
    job = st.jobs.create("fix", meta={"fix_id": "IP-09", "auto": "gateway"})
    if not st.jobs.try_mark_fix_started(job.id):
        st.jobs.cancel(job.id)
        return _err("fix_in_progress", "Another fix is already running.", 409)
    st.logger.confirmation("gateway_configure:IP-09", True, source="web", auto=True)

    def work(_job):  # type: ignore[no-untyped-def]
        try:
            result = auto_configure_gateway(st.runtime)
            st.logger.action(
                "web",
                "gateway_configure",
                status=result.status,
                adapter=result.adapter,
                gateway=result.gateway,
            )
            if result.outcome is not None:
                st.logger.fix_applied(result.fix_id, status=result.status, source="web", auto=True)
            return result.to_dict()
        finally:
            st.jobs.mark_fix_finished(job.id)

    st.jobs.submit(job, work)
    return jsonify({"job_id": job.id, "fix_id": "IP-09"})


@api_bp.post("/fix/execute")
def api_fix_execute():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    token = str(body.get("confirmation_token") or "")
    with _FIX_PLANS_LOCK:
        record = _FIX_PLANS.get(token)
        if not record or record.get("used"):
            st.logger.event("security_rejected", source="web", reason="invalid_or_used_token")
            return _err("invalid_token", "Invalid or used confirmation token.", 403)
        if time.time() > float(record.get("expires", 0)):
            st.logger.event("security_rejected", source="web", reason="expired_token")
            return _err("expired_token", "Confirmation token expired.", 403)
        entry = record["entry"]
        plan = record["plan"]
        if str(getattr(entry, "risk", "")).lower() == "high" and body.get("second_confirmation") is not True:
            st.logger.event("security_rejected", source="web", reason="risk_h_second_confirmation_missing", fix_id=entry.id)
            return _err("second_confirmation_required", "High-risk fix requires second confirmation.", 403)
        dry_run = body.get("dry_run") is True
        job = st.jobs.create("fix", meta={"fix_id": entry.id, "dry_run": dry_run})
        if not st.jobs.try_mark_fix_started(job.id):
            st.jobs.cancel(job.id)
            return _err("fix_in_progress", "Another fix is already running.", 409)
        record["used"] = True
    st.logger.confirmation(f"fix_execute:{entry.id}", True, source="web", dry_run=dry_run)

    def work(_job):  # type: ignore[no-untyped-def]
        def report(event):  # type: ignore[no-untyped-def]
            _job.events.put({"type": "fix_progress", **event})

        try:
            executor = st.runtime.executor()
            outcome = executor.run(
                entry,
                plan=plan,
                assume_yes=True,
                dry_run=dry_run,
                confirm=lambda _q: True,
                isolation=lambda: body.get("another_device_works"),
                progress=report,
            )
            st.logger.fix_applied(entry.id, status=outcome.status, source="web", dry_run=dry_run)
            return outcome.to_dict()
        finally:
            st.jobs.mark_fix_finished(job.id)

    st.jobs.submit(job, work)
    return jsonify({"job_id": job.id, "fix_id": entry.id})


@api_bp.post("/fix/rollback")
def api_fix_rollback():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    if body.get("confirmed") is not True:
        return _err("confirmation_required", "Rollback requires explicit confirmation.", 403)
    fix_id = str(body.get("fix_id") or "")
    if not fix_id:
        return _err("missing_fix_id", "fix_id is required", 400)
    try:
        entry = st.runtime.catalog.require(fix_id)
    except Exception:
        return _err("unknown_fix_id", f"Unknown fix id: {fix_id}", 404)
    job = st.jobs.create("rollback", meta={"fix_id": fix_id})
    if not st.jobs.try_mark_fix_started(job.id):
        st.jobs.cancel(job.id)
        return _err("fix_in_progress", "Another fix is already running.", 409)

    def work(_job):  # type: ignore[no-untyped-def]
        try:
            executor = st.runtime.executor()
            outcome = executor.rollback(entry, assume_yes=True, confirm=lambda _q: True)
            st.logger.action("web", "fix_rollback", fix_id=fix_id, status=outcome.status)
            return outcome.to_dict()
        finally:
            st.jobs.mark_fix_finished(job.id)

    st.jobs.submit(job, work)
    return jsonify({"job_id": job.id, "fix_id": fix_id})


@api_bp.get("/fix/history")
def api_fix_history():  # type: ignore[no-untyped-def]
    backup_dir = config.backup_dir()
    history = []
    try:
        backups = sorted(backup_dir.glob("*-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        backups = []
    for path in backups[:100]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fix_id = str(data.get("fix_id") or "")
        if not fix_id:
            continue
        history.append({
            "fix_id": fix_id,
            "name": str(data.get("name") or fix_id),
            "captured_at": data.get("captured_at"),
            "rollback_available": True,
        })
    return jsonify({"history": history})


@api_bp.post("/unresolved/answer")
def api_unresolved_answer():  # type: ignore[no-untyped-def]
    st = _state()
    body = _json_body()
    ans = body.get("another_device_works")
    if ans in ("yes", True, "true", 1):
        val = True
    elif ans in ("no", False, "false", 0):
        val = False
    else:
        val = None
    fix_id = body.get("fix_id")
    sections = []
    if fix_id:
        try:
            entry = st.runtime.catalog.require(str(fix_id))
            sections = [unresolved_section(entry, another_device_works=val)]
        except Exception:
            pass
    st.logger.action("web", "unresolved_answer", answer=ans, fix_id=fix_id)
    return jsonify({"another_device_works": val, "sections": sections})



@api_bp.get("/devices")
def api_devices():  # type: ignore[no-untyped-def]
    st = _state()
    force = (request.args.get("force") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        result = st.runtime.monitoring.request_devices(force=force)
    except Exception as exc:  # noqa: BLE001
        return _monitoring_failure(
            st,
            "monitoring_devices_failed",
            "devices_failed",
            str(exc) or "Device discovery failed.",
        )
    if result.state == "pending":
        return jsonify({"state": "pending"}), 202
    if result.state == "error":
        return _monitoring_failure(
            st,
            "monitoring_devices_failed",
            "devices_failed",
            result.error or "Device discovery failed.",
        )
    if result.state != "ready" or result.value is None:
        return _monitoring_failure(
            st,
            "monitoring_devices_invalid_result",
            "devices_failed",
            "Device discovery returned an invalid result.",
        )
    return jsonify({"devices": result.value})


@api_bp.get("/packet-loss")
def api_packet_loss():  # type: ignore[no-untyped-def]
    st = _state()
    try:
        result = st.runtime.monitoring.request_packet_loss()
    except Exception as exc:  # noqa: BLE001
        return _monitoring_failure(
            st,
            "monitoring_packet_loss_failed",
            "packet_loss_failed",
            str(exc) or "Packet-loss collection failed.",
        )
    if result.state == "pending":
        return jsonify({"state": "pending"}), 202
    if result.state == "error":
        return _monitoring_failure(
            st,
            "monitoring_packet_loss_failed",
            "packet_loss_failed",
            result.error or "Packet-loss collection failed.",
        )
    if result.state != "ready" or result.value is None:
        return _monitoring_failure(
            st,
            "monitoring_packet_loss_invalid_result",
            "packet_loss_failed",
            "Packet-loss collection returned an invalid result.",
        )
    return jsonify(result.value)
