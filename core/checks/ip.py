"""IP configuration, DHCP and routing checks (IP-01 .. IP-07)."""

from __future__ import annotations

import ipaddress
from typing import Any

from core.checks.context import (
    CheckContext,
    as_network,
    interface_ipv4,
    skipped,
    text,
    truthy,
)
from core.models import CheckResult, Layer, Status

LAYER = Layer.IP

_VIRTUAL_HINTS = (
    "hyper-v",
    "vethernet",
    "vmware",
    "virtualbox",
    "wsl",
    "vpn",
    "tap",
    "wireguard",
    "tailscale",
    "docker",
    "bluetooth",
    "wi-fi direct",
    "local area connection*",
    "npcap",
    "loopback",
)


def _adapter_index(ctx: CheckContext) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in ctx.snapshot.section("adapters"):
        name = text(row.get("Name")).lower()
        if name:
            mapping[name] = row
    return mapping


def _is_virtual_adapter(row: dict[str, Any]) -> bool:
    if truthy(row.get("Virtual")):
        return True
    haystack = f"{text(row.get('Name'))} {text(row.get('InterfaceDescription'))}".lower()
    return any(hint in haystack for hint in _VIRTUAL_HINTS)


def _relevant_address(ctx: CheckContext, row: dict[str, Any], adapters: dict[str, dict[str, Any]]) -> bool:
    """Ignore APIPA/stale addresses on virtual, disconnected or Bluetooth adapters."""

    alias = text(row.get("InterfaceAlias")).lower()
    adapter = adapters.get(alias)
    if adapter is None:
        return not any(hint in alias for hint in _VIRTUAL_HINTS)
    if text(adapter.get("Status")).strip().lower() not in {"up", ""}:
        return False
    return not _is_virtual_adapter(adapter)


def _virtual_aliases(ctx: CheckContext) -> set[str]:
    aliases = {
        text(row.get("Name")).lower()
        for row in ctx.snapshot.section("adapters")
        if _is_virtual_adapter(row)
    }
    for row in ctx.snapshot.section("ip_addresses"):
        alias = text(row.get("InterfaceAlias")).lower()
        if any(hint in alias for hint in _VIRTUAL_HINTS):
            aliases.add(alias)
    return aliases


def _default_routes(ctx: CheckContext) -> list[dict[str, Any]]:
    rows = [
        row
        for row in ctx.snapshot.section("routes")
        if text(row.get("DestinationPrefix")).strip() == "0.0.0.0/0"
    ]
    if rows:
        return rows

    from core.native import parse_default_routes

    return parse_default_routes(ctx.snapshot.native_text("route_print"))


def run(ctx: CheckContext) -> list[CheckResult]:
    if not ctx.is_windows:
        return [skipped(LAYER, "IP-01", "IP configuration", "Windows-only check")]

    addresses = interface_ipv4(ctx.snapshot)
    if not addresses:
        return [
            skipped(
                LAYER,
                "IP-01",
                "IP configuration",
                "No usable IPv4 address/configuration was reported.",
            )
        ]

    adapters = _adapter_index(ctx)
    results: list[CheckResult] = []

    apipa = [
        text(row.get("IPAddress"))
        for row in addresses
        if text(row.get("IPAddress")).startswith("169.254.")
        and _relevant_address(ctx, row, adapters)
    ]
    results.append(
        CheckResult(
            id="IP-01",
            layer=LAYER,
            status=Status.FAIL if apipa else Status.PASS,
            title="DHCP lease / APIPA",
            message=(
                "Automatic private address(es): " + ", ".join(apipa)
                if apipa
                else "No APIPA (169.254.x.x) address found."
            ),
            cause=(
                "The device has a 169.254.x.x address, meaning DHCP did not provide a lease."
                if apipa
                else None
            ),
            evidence={"apipa": apipa},
            fix_ids=["IP-01"] if apipa else [],
        )
    )

    duplicate = [
        text(row.get("IPAddress"))
        for row in addresses
        if text(row.get("AddressState")).strip().lower() == "duplicate"
        and _relevant_address(ctx, row, adapters)
    ]
    results.append(
        CheckResult(
            id="IP-03",
            layer=LAYER,
            status=Status.FAIL if duplicate else Status.PASS,
            title="Duplicate address",
            message=(
                "Windows detected a duplicate IP: " + ", ".join(duplicate)
                if duplicate
                else "No duplicate IPv4 address detected."
            ),
            cause="Another device on the LAN is using the same address." if duplicate else None,
            evidence={"duplicate": duplicate},
            fix_ids=["IP-03"] if duplicate else [],
        )
    )

    gateway = ctx.snapshot.gateway
    mismatch: list[dict[str, Any]] = []
    stale_lease: list[dict[str, Any]] = []
    if gateway:
        try:
            gateway_ip = ipaddress.ip_address(gateway)
        except ValueError:
            gateway_ip = None
        if gateway_ip is not None:
            for row in addresses:
                address_text = text(row.get("IPAddress"))
                if address_text.startswith("169.254.") or not _relevant_address(ctx, row, adapters):
                    continue
                network = as_network(address_text, row.get("PrefixLength"))
                if network is None or gateway_ip not in network:
                    item = {
                        "address": text(row.get("IPAddress")),
                        "prefix": text(row.get("PrefixLength")),
                        "gateway": gateway,
                        "origin": text(row.get("PrefixOrigin")),
                    }
                    if text(row.get("PrefixOrigin")).strip().lower() == "manual":
                        mismatch.append(item)
                    else:
                        stale_lease.append(item)

    results.append(
        CheckResult(
            id="IP-04",
            layer=LAYER,
            status=Status.WARN if mismatch else Status.PASS,
            title="Static address matches the network",
            message=(
                "Static address is outside the gateway subnet: "
                + ", ".join(item["address"] + "/" + item["prefix"] for item in mismatch)
                if mismatch
                else "No obviously wrong static address found."
            ),
            cause="A static IP/mask/gateway from another network is still configured." if mismatch else None,
            evidence={"mismatch": mismatch},
            fix_ids=["IP-04"] if mismatch else [],
        )
    )

    results.append(
        CheckResult(
            id="IP-02",
            layer=LAYER,
            status=Status.WARN if stale_lease else Status.PASS,
            title="DHCP lease matches the network",
            message=(
                "DHCP address is outside the gateway subnet: "
                + ", ".join(item["address"] + "/" + item["prefix"] for item in stale_lease)
                if stale_lease
                else "DHCP address is on the gateway subnet."
            ),
            cause="A stale lease may remain after moving between networks." if stale_lease else None,
            evidence={"stale": stale_lease},
            fix_ids=["IP-02"] if stale_lease else [],
        )
    )

    default_routes = _default_routes(ctx)
    active = [row for row in addresses if text(row.get("AddressState")).strip().lower() in {"", "preferred", "tentative"}]
    have_route_source = bool(ctx.snapshot.section("routes")) or bool(ctx.snapshot.native_text("route_print"))
    results.append(
        CheckResult(
            id="IP-05",
            layer=LAYER,
            status=(
                Status.SKIP
                if not have_route_source
                else (Status.FAIL if not default_routes and active else Status.PASS)
            ),
            title="Default route",
            message=(
                "No default route (0.0.0.0/0) is present."
                if have_route_source and not default_routes and active
                else (
                    "Default route is present."
                    if have_route_source
                    else "Route table could not be read."
                )
            ),
            cause="Missing default route means traffic cannot leave the local subnet." if have_route_source and not default_routes and active else None,
            evidence={"default_routes": default_routes},
            fix_ids=["IP-09"] if have_route_source and not default_routes and active else [],
        )
    )

    prefixes: dict[str, set[str]] = {}
    for row in ctx.snapshot.section("routes"):
        prefix = text(row.get("DestinationPrefix")).strip()
        if not prefix or prefix == "0.0.0.0/0":
            continue
        prefixes.setdefault(prefix, set()).add(text(row.get("NextHop")))
    duplicates = {prefix: sorted(hops) for prefix, hops in prefixes.items() if len(hops) > 1}
    persistent = [
        text(row.get("DestinationPrefix"))
        for row in ctx.snapshot.section("routes")
        if text(row.get("Store")).strip().lower() == "persistent"
    ]
    results.append(
        CheckResult(
            id="IP-06",
            layer=LAYER,
            status=Status.WARN if duplicates else Status.PASS,
            title="Overlapping routes",
            message=(
                "Multiple next hops for the same prefix: "
                + ", ".join(duplicates)
                if duplicates
                else "No overlapping route prefixes found."
            ),
            cause="Leftover VPN/virtual switch routes can override normal routing." if duplicates else None,
            evidence={"duplicates": duplicates, "persistent_routes": persistent},
            fix_ids=["IP-06"] if duplicates else [],
        )
    )

    virtual_aliases = _virtual_aliases(ctx)
    physical_networks = []
    virtual_networks = []
    for row in addresses:
        network = as_network(text(row.get("IPAddress")), row.get("PrefixLength"))
        if network is None:
            continue
        alias = text(row.get("InterfaceAlias")).lower()
        if alias in virtual_aliases:
            virtual_networks.append((alias, network))
        elif _relevant_address(ctx, row, adapters):
            physical_networks.append((alias, network))

    overlaps = []
    for virtual_alias, virtual_network in virtual_networks:
        for physical_alias, physical_network in physical_networks:
            if virtual_network.overlaps(physical_network):
                overlaps.append(
                    {
                        "virtual": virtual_alias,
                        "physical": physical_alias,
                        "prefix": str(virtual_network),
                    }
                )

    results.append(
        CheckResult(
            id="IP-07",
            layer=LAYER,
            status=Status.WARN if overlaps else Status.PASS,
            title="Virtual network overlap",
            message=(
                "Virtual adapter subnet overlaps a real LAN: "
                + ", ".join(f"{item['virtual']} vs {item['physical']}" for item in overlaps)
                if overlaps
                else "No virtual adapter subnet overlaps the physical LAN."
            ),
            cause=(
                "Docker/WSL/Hyper-V/VPN ranges can shadow real LAN addresses."
                if overlaps
                else None
            ),
            evidence={"overlaps": overlaps},
            fix_ids=["IP-07"] if overlaps else [],
            detection_only=bool(overlaps),
        )
    )

    return results
