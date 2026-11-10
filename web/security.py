"""Security helpers: session token, Host/Origin checks, CSP headers."""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlparse

from flask import Request, Response, abort, g, request

TOKEN_COOKIE = "netscope_session"
TOKEN_HEADER = "X-NetScope-Token"
TOKEN_PARAM = "token"

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class WebSecurity:
    session_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    boot_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    issued_at: float = field(default_factory=time.monotonic)

    def allowed_hosts(self, port: int | None) -> set[str]:
        hosts = {"127.0.0.1", "localhost", "::1", "[::1]"}
        if port:
            hosts.update({f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"})
        return hosts

    def host_ok(self, req: Request, port: int | None) -> bool:
        host = (req.host or "").lower()
        allowed = {h.lower() for h in self.allowed_hosts(port)}
        return host in allowed

    def origin_ok(self, req: Request, port: int | None) -> bool:
        origin = req.headers.get("Origin") or req.headers.get("Referer")
        if not origin:
            return False
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"}:
            return False
        netloc = (parsed.netloc or "").lower()
        return netloc in {h.lower() for h in self.allowed_hosts(port)}

    def issue_cookie(self, response: Response) -> None:
        response.set_cookie(
            TOKEN_COOKIE,
            self.session_token,
            httponly=True,
            samesite="Strict",
            secure=False,  # 127.0.0.1 only
            path="/",
        )

    def cookie_valid(self, req: Request) -> bool:
        value = req.cookies.get(TOKEN_COOKIE, "")
        return bool(value) and hmac.compare_digest(value, self.session_token)

    def header_valid(self, req: Request) -> bool:
        value = req.headers.get(TOKEN_HEADER, "")
        return bool(value) and hmac.compare_digest(value, self.session_token)

    def boot_valid(self, token: str) -> bool:
        return bool(token) and hmac.compare_digest(token, self.boot_token)


def apply_security_headers(response: Response) -> Response:
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


def require_api_security(sec: WebSecurity, port: int | None) -> None:
    if not sec.host_ok(request, port):
        abort(403, description="host rejected")
    if not sec.cookie_valid(request):
        abort(401, description="authentication required")
    if request.method not in _SAFE_METHODS:
        if not sec.origin_ok(request, port):
            abort(403, description="origin rejected")
        if not request.is_json and request.content_length not in (None, 0):
            abort(415, description="json required")
        if not sec.header_valid(request):
            abort(403, description="token header required")
