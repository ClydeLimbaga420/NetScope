"""Gateway reachability checks."""

from __future__ import annotations

from core.checks.context import CheckContext, skipped, text
from core.models import CheckResult, Layer, Status

LAYER = Layer.GATEWAY


def _neighbor_state(ctx: CheckContext, gateway: str) -> str | None:
    for row in ctx.snapshot.section("neighbors"):
        if text(row.get("IPAddress")) == gateway:
            return text(row.get("State")).strip().lower() or None

    from core.native import parse_arp

    for row in parse_arp(ctx.snapshot.native_text("arp")):
        if row["ip"] == gateway:
            return row.get("type", "").lower() or None
    return None


def run(ctx: CheckContext) -> list[CheckResult]:
    if not ctx.is_windows:
        return [skipped(LAYER, "GW-01", "Gateway", "Windows-only check")]

    gateway = ctx.snapshot.gateway
    if not gateway:
        return [
            skipped(
                LAYER,
                "GW-01",
                "Gateway",
                "No default gateway was detected; see the IP configuration layer.",
            )
        ]

    ping = ctx.snapshot.pings.get(gateway)
    state = _neighbor_state(ctx, gateway)
    evidence = {
        "gateway": gateway,
        "ping": ping.to_dict() if ping else None,
        "neighbor_state": state,
    }

    if ping is None:
        return [skipped(LAYER, "GW-01", "Gateway", "Gateway was not pinged.")]

    if ping.online:
        return [
            CheckResult(
                id="GW-01",
                layer=LAYER,
                status=Status.PASS,
                title="Gateway reachable",
                message=f"Gateway {gateway} answered in {ping.latency_ms or '?'} ms.",
                evidence=evidence,
            )
        ]

    incomplete = state in {None, "incomplete", "unreachable", "stale"}
    if incomplete:
        return [
            CheckResult(
                id="GW-02",
                layer=LAYER,
                status=Status.FAIL,
                title="Gateway not reachable",
                message=(
                    f"Gateway {gateway} did not answer and its ARP entry is "
                    f"{state or 'missing'}."
                ),
                cause=(
                    "The link may be down, the cable/switch port/AP may be faulty, "
                    "or the gateway (router) is off. This usually cannot be fixed from this PC."
                ),
                evidence=evidence,
                fix_ids=["LAN-01", "LAN-02", "ADP-02"],
                detection_only=True,
            )
        ]

    return [
        CheckResult(
            id="GW-01",
            layer=LAYER,
            status=Status.WARN,
            title="Gateway does not answer ping",
            message=(
                f"Gateway {gateway} did not answer ICMP but its ARP entry is '{state}'."
            ),
            cause="The router may block ICMP; test a TCP port before treating this as a failure.",
            evidence=evidence,
            fix_ids=[],
        )
    ]
