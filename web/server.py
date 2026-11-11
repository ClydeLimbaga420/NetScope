"""Flask app factory and server lifecycle for the NetScope web UI."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from flask import Flask, jsonify, redirect, request, url_for

import config
from cli.admin import is_admin
from core.engine import DiagnosticEngine
from core.logging_config import setup_logging
from core.probes import NetworkProbe
from core.runner import SubprocessRunner
from fixes.catalog import load_catalog
from gui.runtime import GuiRuntime, empty_catalog
from powershell.runner import PowerShellLayer
from web.api import api_bp
from web.jobs import JobManager
from web.pages import pages_bp
from web.paths import web_root
from web.security import TOKEN_PARAM, WebSecurity, apply_security_headers, require_api_security


class _WerkzeugToNetScope(logging.Handler):
    def __init__(self, logger: Any) -> None:
        super().__init__(level=logging.INFO)
        self._logger = logger

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if msg:
                self._logger.event("werkzeug", source="web", message=msg, level=record.levelname)
        except Exception:
            pass


def _configure_werkzeug(logger: Any) -> None:
    log = logging.getLogger("werkzeug")
    log.handlers = [_WerkzeugToNetScope(logger)]
    log.setLevel(logging.INFO)
    log.propagate = False


class WebState:
    def __init__(self, mode: str = "web") -> None:
        self.mode = mode
        self.port: int | None = None
        self.security = WebSecurity()
        self.jobs = JobManager()
        self.logger = setup_logging(mode)
        self.session_id = getattr(self.logger, "session_id", "-")
        self.runtime = self._build_runtime()
        self.last_heartbeat = time.monotonic()
        self.shutdown_event = threading.Event()
        self.fix_lock = threading.Lock()
        self.last_snapshot: Any = None
        self.last_report: Any = None

    def _build_runtime(self) -> GuiRuntime:
        runner = SubprocessRunner(self.logger)
        ps = PowerShellLayer(runner, self.logger)
        engine = DiagnosticEngine(runner=runner, ps=ps, logger=self.logger, probe=NetworkProbe())
        try:
            catalog = load_catalog()
        except Exception as exc:
            self.logger.warning("fix_catalog_unavailable", source="web", error=str(exc))
            catalog = empty_catalog()
        return GuiRuntime(
            engine=engine,
            catalog=catalog,
            runner=runner,
            ps=ps,
            logger=self.logger,
            admin_check=is_admin,
            session_id=self.session_id,
            backup_dir=config.backup_dir(),
        )

    def touch(self) -> None:
        self.last_heartbeat = time.monotonic()

    def should_shutdown(self) -> bool:
        if (time.monotonic() - self.last_heartbeat) <= 20:
            return False
        return not self.jobs.has_active_jobs()


def create_app(state: WebState | None = None) -> Flask:
    state = state or WebState()
    root = web_root()
    app = Flask(
        __name__,
        template_folder=str(root / "templates"),
        static_folder=str(root / "static"),
        static_url_path="/static",
    )
    app.config["JSON_SORT_KEYS"] = False
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.extensions["netscope_state"] = state
    _configure_werkzeug(state.logger)

    @app.before_request
    def _before() -> Any:
        st: WebState = app.extensions["netscope_state"]
        if not st.security.host_ok(request, st.port):
            return jsonify({"error": {"code": "host_rejected", "message": "Host not allowed."}}), 403
        path = request.path or ""
        if path.startswith("/api/"):
            try:
                require_api_security(st.security, st.port)
            except Exception as exc:  # abort raises
                from werkzeug.exceptions import HTTPException
                if isinstance(exc, HTTPException):
                    st.logger.event(
                        "security_rejected",
                        source="web",
                        path=path,
                        status=exc.code,
                        reason=str(exc.description or "rejected"),
                    )
                    code = "unauthorized" if exc.code == 401 else "forbidden"
                    msg = exc.description or "Request rejected."
                    if exc.code == 415:
                        code = "unsupported_media_type"
                    return jsonify({"error": {"code": code, "message": str(msg)}}), exc.code
                raise
            st.logger.event("api_request", source="web", method=request.method, path=path)
        return None

    @app.after_request
    def _after(response):  # type: ignore[no-untyped-def]
        resp = apply_security_headers(response)
        st: WebState = app.extensions["netscope_state"]
        if request.path.startswith("/api/"):
            st.logger.event(
                "api_response",
                source="web",
                method=request.method,
                path=request.path,
                status=resp.status_code,
            )
        return resp

    @app.route("/__boot__")
    def _boot():  # type: ignore[no-untyped-def]
        st: WebState = app.extensions["netscope_state"]
        token = request.args.get(TOKEN_PARAM, "")
        if not st.security.boot_valid(token):
            return jsonify({"error": {"code": "invalid_boot_token", "message": "Invalid launch token."}}), 403
        resp = redirect("/")
        st.security.issue_cookie(resp)
        # also make token available to JS? no, must keep clean URL and cookie/httpOnly; client will need header token via separate bootstrap endpoint after cookie? but header requires knowing token - design says "server exchanges it for HttpOnly..." and "All state-changing requests (POST) additionally require a custom header (X-NetScope-Token)". That means client must know token; cannot be HttpOnly-only for header. We'll set a non-HttpOnly readable companion cookie is insecure for XSS but CSP strict; better provide token via authenticated bootstrap JSON and keep in memory.
        st.logger.event("session_boot", source="web")
        return resp

    @app.get("/__session__")
    def _session():  # type: ignore[no-untyped-def]
        st: WebState = app.extensions["netscope_state"]
        if not st.security.cookie_valid(request):
            return jsonify({"error": {"code": "unauthorized", "message": "No session."}}), 401
        # provide header token for JS to send on POST (memory only in JS)
        return jsonify({"token": st.security.session_token, "session_id": st.session_id})

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.errorhandler(404)
    def _404(_e):  # type: ignore[no-untyped-def]
        if request.path.startswith("/api/"):
            return jsonify({"error": {"code": "not_found", "message": "Not found."}}), 404
        return "Not found", 404

    @app.errorhandler(400)
    def _400(e):  # type: ignore[no-untyped-def]
        if request.path.startswith("/api/"):
            return jsonify({"error": {"code": "bad_request", "message": getattr(e, "description", "Bad request")}}), 400
        return "Bad request", 400

    @app.errorhandler(500)
    def _500(e):  # type: ignore[no-untyped-def]
        st: WebState = app.extensions["netscope_state"]
        st.logger.error("web_error", source="web", error=str(e), exc_info=True)
        if request.path.startswith("/api/"):
            return jsonify({"error": {"code": "internal_error", "message": "Internal server error."}}), 500
        return "Internal server error", 500

    return app
