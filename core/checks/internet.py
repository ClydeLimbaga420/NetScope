"""Internet, captive portal, proxy and clock checks (NET-01 .. NET-06)."""

from __future__ import annotations

from datetime import datetime, timezone

import config
from core.checks.context import CheckContext, skipped, text, truthy
from core.models import CheckResult, Layer, Status
from core.native import parse_netsh_winhttp_proxy

LAYER = Layer.INTERNET


def _proxy_endpoint(value: str) -> tuple[str, int] | None:
    raw = text(value).strip()
    if not raw:
        return None
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            _, _, part = part.partition("=")
        part = part.strip()
        if not part:
            continue
        host, _, port = part.rpartition(":")
        if not host or not port.isdigit():
            continue
        return host.strip("[]"), int(port)
    return None


def run(ctx: CheckContext) -> list[CheckResult]:
    if not ctx.is_windows:
        return [skipped(LAYER, "NET-PING", "Internet", "Windows-only check")]

    results: list[CheckResult] = []
    pings = {
        host: ctx.snapshot.pings.get(host) for host in config.INTERNET_PING_HOSTS
    }
    reachable = {host: result for host, result in pings.items() if result and result.online}
    gateway_ping = ctx.snapshot.pings.get(ctx.snapshot.gateway) if ctx.snapshot.gateway else None

    evidence = {
        "pings": {
            host: result.to_dict() for host, result in pings.items() if result is not None
        },
        "gateway": ctx.snapshot.gateway,
    }

    if not pings or all(result is None for result in pings.values()):
        results.append(skipped(LAYER, "NET-PING", "Internet reachability", "No public host was pinged."))
    elif reachable:
        results.append(
            CheckResult(
                id="NET-PING",
                layer=LAYER,
                status=Status.PASS,
                title="Internet reachability",
                message="At least one public address answered: " + ", ".join(sorted(reachable)),
                evidence=evidence,
            )
        )
    else:
        if gateway_ping is not None and gateway_ping.online:
            cause = (
                "The gateway answers, but public addresses do not. The problem is likely "
                "the router WAN link, the modem, or the ISP."
            )
            next_step = "Check the router/modem WAN status and test another device."
        else:
            cause = (
                "Neither the gateway nor public addresses answer, so this is a local link "
                "or gateway problem before the internet."
            )
            next_step = "Fix the gateway/link layer first."
        results.append(
            CheckResult(
                id="NET-PING",
                layer=LAYER,
                status=Status.FAIL,
                title="Internet unreachable",
                message="No public address responded to ping.",
                cause=cause + " " + next_step,
                evidence=evidence,
                fix_ids=[],
                detection_only=True,
            )
        )

    http_result = ctx.probe.http_get(config.CAPTIVE_PORTAL_URL)
    portal = False
    if http_result.error and http_result.status is None:
        if reachable:
            portal = False
    elif http_result.status is not None and http_result.status not in (200, 204):
        portal = True
    elif http_result.body and config.CAPTIVE_PORTAL_EXPECTED not in http_result.body:
        portal = True

    results.append(
        CheckResult(
            id="NET-01",
            layer=LAYER,
            status=Status.WARN if portal else Status.PASS,
            title="Captive portal",
            message=(
                "The connectivity probe returned a login/redirect page instead of the expected text."
                if portal
                else (
                    "Connectivity probe matched the expected response."
                    if http_result.ok
                    else "Connectivity probe could not be reached (see internet reachability)."
                )
            ),
            cause="A hotel/cafe/campus Wi-Fi portal must be completed before internet access works." if portal else None,
            evidence={
                "url": config.CAPTIVE_PORTAL_URL,
                "status": http_result.status,
                "error": http_result.error,
                "body_sample": http_result.body[:200],
            },
            fix_ids=["NET-01"] if portal else [],
        )
    )

    winhttp = parse_netsh_winhttp_proxy(ctx.snapshot.native_text("winhttp_proxy"))
    winhttp_dead = False
    if winhttp:
        endpoint = _proxy_endpoint(winhttp)
        if endpoint and not ctx.probe.tcp_connect(endpoint[0], endpoint[1], timeout=1.5):
            winhttp_dead = True
    results.append(
        CheckResult(
            id="NET-03",
            layer=LAYER,
            status=Status.WARN if winhttp_dead else Status.PASS,
            title="WinHTTP system proxy",
            message=(
                f"A WinHTTP proxy is configured but unreachable: {winhttp}"
                if winhttp_dead
                else ("WinHTTP is configured to use a proxy." if winhttp else "WinHTTP uses direct access.")
            ),
            cause="A dead system proxy breaks Windows Update, Store and services while browsers may still work." if winhttp_dead else None,
            evidence={"winhttp_proxy": winhttp, "unreachable": winhttp_dead},
            fix_ids=["NET-03"] if winhttp_dead else [],
        )
    )

    proxy_rows = ctx.snapshot.section("system_proxy")
    user_proxy = ""
    user_proxy_dead = False
    if proxy_rows:
        row = proxy_rows[0]
        user_proxy = text(row.get("ProxyServer"))
        if truthy(row.get("ProxyEnable")) and user_proxy:
            endpoint = _proxy_endpoint(user_proxy)
            if endpoint and not ctx.probe.tcp_connect(endpoint[0], endpoint[1], timeout=1.5):
                user_proxy_dead = True
    results.append(
        CheckResult(
            id="NET-04",
            layer=LAYER,
            status=Status.WARN if user_proxy_dead else Status.PASS,
            title="User (WinINET) proxy",
            message=(
                f"The user proxy is enabled but unreachable: {user_proxy}"
                if user_proxy_dead
                else "No dead user proxy detected."
            ),
            cause="A stale per-user proxy setting can break apps that honour it." if user_proxy_dead else None,
            evidence={"proxy_server": user_proxy, "unreachable": user_proxy_dead},
            fix_ids=["NET-04"] if user_proxy_dead else [],
        )
    )

    clock_offset = None
    if http_result.date is not None:
        clock_offset = (datetime.now(timezone.utc) - http_result.date).total_seconds()
    results.append(
        CheckResult(
            id="NET-06",
            layer=LAYER,
            status=Status.WARN if clock_offset is not None and abs(clock_offset) > 300 else Status.PASS,
            title="System clock",
            message=(
                f"The local clock differs from the HTTP Date header by {int(clock_offset)} seconds."
                if clock_offset is not None and abs(clock_offset) > 300
                else (
                    "Clock offset could not be measured."
                    if clock_offset is None
                    else "System clock is within tolerance."
                )
            ),
            cause="A wrong clock breaks TLS/HTTPS even when ping and HTTP work." if clock_offset is not None and abs(clock_offset) > 300 else None,
            evidence={"offset_seconds": clock_offset},
            fix_ids=["NET-06"] if clock_offset is not None and abs(clock_offset) > 300 else [],
        )
    )

    return results
