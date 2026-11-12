"""JSON API routes calling the existing engine/fixes/CLI utilities."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

import config
from cli.admin import is_admin, relaunch_elevated
from cli.render import render_report_text
from cli.utilities import UtilityRunner
from core.info import build_info
from core.logging_config import LOG_FILE_NAME
from fixes.catalog import CatalogError, load_catalog
from fixes.executor import FixExecutor
from fixes.gateway_config import auto_configure_gateway
from fixes.if_unresolved import build_unresolved_sections, unresolved_section
from gui.launch import gui_relaunch_argv
from core.checks.descriptors import CHECK_DESCRIPTORS
from core.models import Layer

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


# --- dashboard compatibility (preserve main features: overview/devices/packet-loss/diagnostics) ---
try:
    import psutil
    from modules.bandwidth import BandwidthMonitor
    from modules.device_scanner import get_arp_devices
    from modules.diagnostics import list_diagnostics as legacy_list_diagnostics, run_diagnostic as legacy_run_diagnostic
    from modules.network_info import get_network_info
    from modules.ping_monitor import ping_host, ping_host_stats
except Exception:  # pragma: no cover
    psutil = None
    BandwidthMonitor = None
    get_arp_devices = None
    legacy_list_diagnostics = None
    legacy_run_diagnostic = None
    get_network_info = None
    ping_host = None
    ping_host_stats = None

_dashboard_bandwidth = BandwidthMonitor() if BandwidthMonitor else None


def _dashboard_status_payload():
    st = _state()
    if not get_network_info or not ping_host or _dashboard_bandwidth is None:
        network = {}
        traffic = {"download_kbps": 0, "upload_kbps": 0}
        internet_ping = {"host": "1.1.1.1", "latency_ms": None, "online": False}
        gateway_ping = {"host": None, "latency_ms": None, "online": False}
        problems = []
    else:
        network = get_network_info()
        traffic = _dashboard_bandwidth.get_rates()
        gateway = network.get("gateway")
        internet_ping = ping_host("1.1.1.1")
        gateway_ping = ping_host(gateway) if gateway else {"host": None, "latency_ms": None, "online": False, "reason": "No default gateway was detected."}
        problems = []
        try:
            # mirror app._status_problems logic lightly
            diagnosis = network.get("diagnosis") or {}
            for issue in (diagnosis.get("issues") or []):
                problems.append({"source": "configuration", "severity": issue.get("severity", "warning"), "message": issue.get("message")})
            if gateway and not (gateway_ping or {}).get("online"):
                problems.append({"source": "gateway", "severity": "error", "message": f"Default gateway {gateway} did not respond."})
            if not (internet_ping or {}).get("online"):
                if gateway and (gateway_ping or {}).get("online"):
                    msg = "The default gateway is reachable, but the internet is not."
                elif gateway:
                    msg = "Network connection problem: the internet is unreachable."
                else:
                    msg = "Network is down or disconnected: no default gateway was detected."
                problems.append({"source": "internet", "severity": "error", "message": msg})
            # dedupe
            seen = set(); deduped=[]
            for pr in problems:
                k = pr.get("message")
                if k and k not in seen:
                    seen.add(k); deduped.append(pr)
            problems = deduped
        except Exception:
            pass
    payload = {
        "network": network,
        "traffic": traffic,
        "internet_ping": internet_ping,
        "gateway_ping": gateway_ping,
        "problems": problems,
        # web/engine meta (non-breaking extra keys)
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "admin": bool(is_admin()),
        "session_id": st.session_id,
        "dry_run_default": False,
        "powershell": {"available": True if getattr(st.runtime, "ps", None) is not None else None},
    }
    return payload


@api_bp.get("/status")
def api_status():  # type: ignore[no-untyped-def]
    return jsonify(_dashboard_status_payload())


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
        snap = runtime.engine.collect_snapshot()
        st.last_snapshot = snap

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
    snap = st.last_snapshot
    if snap is None:
        try:
            snap = st.runtime.engine.collect_snapshot()
            st.last_snapshot = snap
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
    allowed = {"ping", "trace", "dns", "arp", "routes", "ports", "mtu"}
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
            snap = st.runtime.engine.collect_snapshot()
            st.last_snapshot = snap
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
    try:
        launched = relaunch_elevated(gui_relaunch_argv())
    except Exception as exc:  # noqa: BLE001
        st.logger.error("elevate_failed", source="web", error=str(exc), exc_info=True)
        return _err("elevate_failed", str(exc), 500)
    if not launched:
        st.logger.action("web", "elevate_cancelled")
        return _err("elevate_cancelled", "Administrator elevation was cancelled.", 409)
    st.logger.action("web", "elevate_requested")
    st.shutdown_event.set()
    return jsonify({"ok": True})


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
        snap = st.last_snapshot or st.runtime.engine.collect_snapshot()
        st.last_snapshot = snap
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
        try:
            executor = st.runtime.executor()
            outcome = executor.run(
                entry,
                plan=plan,
                assume_yes=True,
                dry_run=dry_run,
                confirm=lambda _q: True,
                isolation=lambda: body.get("another_device_works"),
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
    if not get_arp_devices:
        return jsonify({"devices": []})
    try:
        return jsonify({"devices": get_arp_devices()})
    except Exception as exc:  # noqa: BLE001
        return _err("devices_failed", str(exc), 500)


@api_bp.get("/packet-loss")
def api_packet_loss():  # type: ignore[no-untyped-def]
    if not get_network_info or not ping_host_stats:
        return jsonify({"count": 10, "internet": {}, "gateway": {}})
    network = get_network_info()
    gateway = network.get("gateway")
    count = 10
    def internet():
        return ping_host_stats("1.1.1.1", count=count)
    def gateway_ping():
        if not gateway:
            return {"host": None, "latency_ms": None, "online": False, "packet_loss_percent": None, "packets_sent": 0, "packets_received": 0, "reason": "No default gateway was detected."}
        return ping_host_stats(gateway, count=count)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        inf = ex.submit(internet)
        gw = ex.submit(gateway_ping)
        return jsonify({"count": count, "internet": inf.result(), "gateway": gw.result()})


@api_bp.get("/diagnostics")
def api_diagnostics():  # type: ignore[no-untyped-def]
    # legacy troubleshoot registry (main feature) kept intact
    if not legacy_list_diagnostics:
        return jsonify({"steps": [], "elevated": is_admin(), "check_count": 0, "repair_count": 0})
    try:
        return jsonify(legacy_list_diagnostics())
    except Exception as exc:  # noqa: BLE001
        return _err("diagnostics_failed", str(exc), 500)


@api_bp.post("/diagnostics/<step_id>/run")
def api_run_diagnostic(step_id: str):  # type: ignore[no-untyped-def]
    if not legacy_run_diagnostic:
        return _err("diagnostics_unavailable", "Diagnostics not available.", 500)
    try:
        return jsonify(legacy_run_diagnostic(step_id))
    except KeyError:
        return jsonify({"error": "Unknown diagnostic step"}), 404
    except Exception as exc:  # noqa: BLE001
        return _err("diagnostic_run_failed", str(exc), 500)

