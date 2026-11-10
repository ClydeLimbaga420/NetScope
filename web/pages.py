"""Page routes for the web UI."""

from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from web.security import TOKEN_COOKIE

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def index():  # type: ignore[no-untyped-def]
    st = current_app.extensions["netscope_state"]
    # allow if cookie valid; if not, page will try bootstrap and show message (boot redirect sets cookie)
    return render_template("index.html")


@pages_bp.get("/health")
def health():  # type: ignore[no-untyped-def]
    return "ok"
