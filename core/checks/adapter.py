"""Adapter and driver checks (ADP-01 .. ADP-06)."""

from __future__ import annotations

from typing import Any

from core.checks.context import (
    CheckContext,
    parse_speed_mbps,
    row_state,
    skipped,
    text,
    truthy,
)
from core.models import CheckResult, Layer, Status

LAYER = Layer.ADAPTER

_VIRTUAL_HINTS = (
    "hyper-v",
    "vethernet",
    "virtual",
    "vmware",
    "virtualbox",
    "wsl",
    "loopback",
    "tap-",
    "tap adapter",
    "wireguard",
    "tailscale",
    "zerotier",
    "vpn",
    "docker",
)


def _is_virtual(row: dict[str, Any]) -> bool:
    if truthy(row.get("Virtual")):
        return True
    haystack = f"{text(row.get('Name'))} {text(row.get('InterfaceDescription'))}".lower()
    return any(hint in haystack for hint in _VIRTUAL_HINTS)


def _is_wifi(row: dict[str, Any]) -> bool:
    haystack = f"{text(row.get('Name'))} {text(row.get('InterfaceDescription'))}".lower()
    return any(hint in haystack for hint in ("wi-fi", "wifi", "wireless", "wlan", "802.11"))


def _is_wired(row: dict[str, Any]) -> bool:
    if _is_wifi(row) or _is_virtual(row):
        return False
    return "802.3" in text(row.get("MediaType")).lower() or "ethernet" in text(
        row.get("PhysicalMediaType")
    ).lower() or "ethernet" in text(row.get("InterfaceDescription")).lower()


def run(ctx: CheckContext) -> list[CheckResult]:
    if not ctx.is_windows:
        return [skipped(LAYER, "ADP-01", "Adapter status", "Windows-only check")]

    adapters = ctx.snapshot.section("adapters")
    if not adapters:
        return [
            CheckResult(
                id="ADP-01",
                layer=LAYER,
                status=Status.FAIL,
                title="No network adapter detected",
                message="Windows did not report any network adapter.",
                cause="The adapter may be disabled in BIOS/UEFI, missing a driver, or a hardware fault.",
                evidence={"adapters": []},
                fix_ids=["ADP-01", "ADP-04"],
                detection_only=True,
            )
        ]

    results: list[CheckResult] = []

    disabled = [row for row in adapters if row_state(row) == "disabled"]
    results.append(
        CheckResult(
            id="ADP-01",
            layer=LAYER,
            status=Status.FAIL if disabled else Status.PASS,
            title="Adapter enabled",
            message=(
                "Disabled adapter(s): " + ", ".join(text(row.get("Name")) for row in disabled)
                if disabled
                else "All detected adapters are enabled."
            ),
            cause="The adapter is administratively disabled." if disabled else None,
            evidence={"disabled": [text(row.get("Name")) for row in disabled]},
            fix_ids=["ADP-01"] if disabled else [],
        )
    )

    broken_pnp = []
    critical_problem_codes = {10, 28, 31, 43}
    ignored_devices = ("bluetooth", "wan miniport", "kernel debug", "wi-fi direct", "loopback")
    for row in ctx.snapshot.section("pnp_network_devices"):
        status = text(row.get("Status")).strip().lower()
        problem = row.get("Problem")
        name = text(row.get("FriendlyName"))
        try:
            problem_code = int(problem)
        except (TypeError, ValueError):
            problem_code = 0
        if status == "error" or problem_code in critical_problem_codes or status == "degraded":
            if any(hint in name.lower() for hint in ignored_devices):
                continue
            broken_pnp.append(
                {
                    "device": name,
                    "status": text(row.get("Status")),
                    "problem": problem,
                    "problem_description": text(row.get("ProblemDescription")),
                }
            )
    results.append(
        CheckResult(
            id="ADP-04",
            layer=LAYER,
            status=Status.FAIL if broken_pnp else Status.PASS,
            title="Driver health",
            message=(
                "Network device(s) report an error: "
                + ", ".join(item["device"] or "unknown device" for item in broken_pnp)
                if broken_pnp
                else "No network device reports a driver error."
            ),
            cause=(
                "The driver failed to start (often Code 10/43) or the device is degraded."
                if broken_pnp
                else None
            ),
            evidence={"devices": broken_pnp},
            fix_ids=["ADP-04"] if broken_pnp else [],
        )
    )

    slow = []
    for row in adapters:
        if row_state(row) != "up" or not _is_wired(row):
            continue
        speed = parse_speed_mbps(row.get("LinkSpeed"))
        if speed is not None and speed <= 10:
            slow.append({"name": text(row.get("Name")), "link_speed": text(row.get("LinkSpeed"))})
    results.append(
        CheckResult(
            id="ADP-05",
            layer=LAYER,
            status=Status.WARN if slow else Status.PASS,
            title="Link speed",
            message=(
                "Adapter negotiated a very low speed: "
                + ", ".join(f"{item['name']} ({item['link_speed']})" for item in slow)
                if slow
                else "Wired adapters negotiated a normal link speed."
            ),
            cause=(
                "A 10 Mbps/half-duplex link usually means a bad cable, a failing switch port, "
                "or a driver speed/duplex setting."
                if slow
                else None
            ),
            evidence={"slow_adapters": slow},
            fix_ids=["ADP-05"] if slow else [],
        )
    )

    power_saving = []
    for row in ctx.snapshot.section("adapter_power"):
        value = row.get("AllowComputerToTurnOffDevice")
        if truthy(value):
            power_saving.append(text(row.get("Name")))
    results.append(
        CheckResult(
            id="ADP-03",
            layer=LAYER,
            status=Status.WARN if power_saving else Status.PASS,
            title="Adapter power saving",
            message=(
                "Windows may power off: " + ", ".join(power_saving)
                if power_saving
                else "Adapters are not configured to be powered off by Windows."
            ),
            cause="Power management can drop the link after sleep." if power_saving else None,
            evidence={"adapters": power_saving},
            fix_ids=["ADP-03"] if power_saving else [],
        )
    )

    virtual_names = {
        text(row.get("Name")).lower(): text(row.get("Name"))
        for row in adapters
        if _is_virtual(row)
    }
    physical_names = {
        text(row.get("Name")).lower(): text(row.get("Name"))
        for row in adapters
        if not _is_virtual(row)
    }
    default_routes = [
        row
        for row in ctx.snapshot.section("routes")
        if text(row.get("DestinationPrefix")).strip() == "0.0.0.0/0"
    ]
    metric_warning = None
    if default_routes and virtual_names and physical_names:
        scored = []
        for row in default_routes:
            alias = text(row.get("InterfaceAlias")).lower()
            try:
                metric = int(row.get("InterfaceMetric") or row.get("RouteMetric") or 9999)
            except (TypeError, ValueError):
                metric = 9999
            scored.append((metric, alias))
        scored.sort()
        best_metric, best_alias = scored[0]
        if best_alias in virtual_names:
            physical_metrics = [metric for metric, alias in scored if alias in physical_names]
            metric_warning = {
                "virtual_adapter": virtual_names[best_alias],
                "metric": best_metric,
                "physical_metric": min(physical_metrics) if physical_metrics else None,
            }
    results.append(
        CheckResult(
            id="ADP-06",
            layer=LAYER,
            status=Status.WARN if metric_warning else Status.PASS,
            title="Interface priority",
            message=(
                f"Virtual adapter '{metric_warning['virtual_adapter']}' has the lowest route metric."
                if metric_warning
                else "No virtual adapter is winning the default route."
            ),
            cause=(
                "A VPN/VM/WSL adapter with a lower metric can capture traffic meant for the physical LAN."
                if metric_warning
                else None
            ),
            evidence={"metric": metric_warning} if metric_warning else {},
            fix_ids=["ADP-06"] if metric_warning else [],
        )
    )

    return results
