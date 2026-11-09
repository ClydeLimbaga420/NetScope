"""TCP/IP stack checks (STK-01, NET-10)."""

from __future__ import annotations

from core.checks.context import CheckContext, skipped, text
from core.models import CheckResult, Layer, Status
from core.native import parse_tcp_autotuning, parse_winsock_catalog

LAYER = Layer.STACK


def run(ctx: CheckContext) -> list[CheckResult]:
    if not ctx.is_windows:
        return [skipped(LAYER, "STK-01", "TCP/IP stack", "Windows-only check")]

    results: list[CheckResult] = []

    catalog = ctx.snapshot.native_text("winsock_catalog")
    third_party = parse_winsock_catalog(catalog) if catalog else []
    results.append(
        CheckResult(
            id="STK-01",
            layer=LAYER,
            status=Status.WARN if third_party else (Status.PASS if catalog else Status.SKIP),
            title="Winsock catalog",
            message=(
                "Third-party layered service provider(s) detected: " + ", ".join(third_party)
                if third_party
                else (
                    "Only Microsoft Winsock entries found."
                    if catalog
                    else "Winsock catalog could not be read."
                )
            ),
            cause=(
                "Leftover third-party LSPs from old security/VPN software can corrupt networking."
                if third_party
                else None
            ),
            evidence={"third_party": third_party},
            fix_ids=["STK-01"] if third_party else [],
            detection_only=True,
        )
    )

    tcp_output = ctx.snapshot.native_text("tcp_global")
    autotuning = parse_tcp_autotuning(tcp_output) if tcp_output else None
    disabled = bool(autotuning and autotuning.strip().lower() in {"disabled", "restricted", "highlyrestricted"})
    results.append(
        CheckResult(
            id="NET-10",
            layer=LAYER,
            status=Status.WARN if disabled else (Status.PASS if autotuning else Status.SKIP),
            title="TCP receive window auto-tuning",
            message=(
                f"Receive Window Auto-Tuning is '{autotuning}', which can reduce throughput."
                if disabled
                else (
                    f"Receive Window Auto-Tuning is '{autotuning}'."
                    if autotuning
                    else "TCP global settings could not be read."
                )
            ),
            cause="Disabled auto-tuning limits throughput, especially to remote hosts." if disabled else None,
            evidence={"autotuning": autotuning},
            fix_ids=["NET-10"] if disabled else [],
        )
    )

    return results
