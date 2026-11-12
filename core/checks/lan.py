"""LAN profile, discovery and SMB checks (LAN-04, LAN-05, LAN-08)."""

from __future__ import annotations

from core.checks.context import CheckContext, skipped, text, truthy
from core.models import CheckResult, Layer, Status
from core.subnets import remote_lan_routes

LAYER = Layer.LAN


def run(ctx: CheckContext) -> list[CheckResult]:
    if not ctx.is_windows:
        return [skipped(LAYER, "LAN-04", "Local network", "Windows-only check")]

    results: list[CheckResult] = []

    public_profiles = [
        text(row.get("Name")) or text(row.get("InterfaceAlias"))
        for row in ctx.snapshot.section("connection_profiles")
        if text(row.get("NetworkCategory")).strip().lower() == "public"
    ]
    results.append(
        CheckResult(
            id="LAN-04",
            layer=LAYER,
            status=Status.WARN if public_profiles else Status.PASS,
            title="Network profile",
            message=(
                "Public network profile(s): " + ", ".join(public_profiles)
                if public_profiles
                else "No public network profile found."
            ),
            cause=(
                "A Public profile blocks discovery and file sharing on what may be a trusted LAN."
                if public_profiles
                else None
            ),
            evidence={"public_profiles": public_profiles},
            fix_ids=["LAN-04"] if public_profiles else [],
        )
    )

    friendly_groups = {
        "@firewallapi.dll,-32752": "Network Discovery",
        "@firewallapi.dll,-28502": "File and Printer Sharing",
    }
    grouped: dict[str, dict[str, Any]] = {}
    for row in ctx.snapshot.section("firewall_discovery_rules"):
        group_key = text(row.get("Group")).lower() or text(row.get("DisplayGroup")).lower()
        if not group_key:
            continue
        group = grouped.setdefault(
            group_key,
            {
                "group": friendly_groups.get(group_key)
                or text(row.get("DisplayGroup"))
                or text(row.get("Group")),
                "enabled": False,
            },
        )
        direction = text(row.get("Direction")).lower()
        action = text(row.get("Action")).lower()
        if direction in {"inbound", "1"} and action in {"allow", "2"} and truthy(row.get("Enabled")):
            group["enabled"] = True

    disabled_rules = [group for group in grouped.values() if not group["enabled"]]

    results.append(
        CheckResult(
            id="LAN-05",
            layer=LAYER,
            status=Status.WARN if disabled_rules else Status.PASS,
            title="Discovery / sharing firewall rules",
            message=(
                f"{len(disabled_rules)} discovery/sharing firewall rule(s) are disabled."
                if disabled_rules
                else "Discovery and file-sharing firewall rules are enabled."
            ),
            cause=(
                "Disabled discovery/sharing rules stop this PC from seeing or sharing with LAN devices."
                if disabled_rules
                else None
            ),
            evidence={"disabled_rules": disabled_rules[:20]},
            fix_ids=["LAN-05"] if disabled_rules else [],
        )
    )

    remote_routes = remote_lan_routes(
        ctx.snapshot.section("ip_addresses"),
        ctx.snapshot.section("routes"),
    )
    route_source = bool(ctx.snapshot.section("routes")) or bool(
        ctx.snapshot.native_text("route_print")
    )
    if not route_source:
        results.append(
            skipped(
                LAYER,
                "LAN-03",
                "Cross-subnet LAN reachability",
                "The routing table could not be read.",
            )
        )
    elif not remote_routes:
        results.append(
            skipped(
                LAYER,
                "LAN-03",
                "Cross-subnet LAN reachability",
                "No additional private LAN subnets are routed from this PC.",
            )
        )
    else:
        checks = []
        for route in remote_routes:
            ping = ctx.snapshot.pings.get(route.next_hop or "")
            if not route.next_hop:
                checks.append(
                    {
                        **route.to_dict(),
                        "status": "no_next_hop",
                        "detail": "The route is on-link but no adapter owns this subnet.",
                    }
                )
            elif ping is None:
                checks.append(
                    {
                        **route.to_dict(),
                        "status": "not_tested",
                        "detail": "No reachability probe was collected for the next hop.",
                    }
                )
            elif ping.online:
                checks.append(
                    {
                        **route.to_dict(),
                        "status": "reachable",
                        "latency_ms": ping.latency_ms,
                    }
                )
            else:
                checks.append(
                    {
                        **route.to_dict(),
                        "status": "unreachable",
                        "detail": ping.error or "The next hop did not answer.",
                    }
                )
        unreachable = [item for item in checks if item["status"] != "reachable"]
        details = ", ".join(
            f"{item['network']} via {item['next_hop'] or 'no next hop'}" for item in unreachable
        )
        results.append(
            CheckResult(
                id="LAN-03",
                layer=LAYER,
                status=Status.WARN if unreachable else Status.PASS,
                title="Cross-subnet LAN reachability",
                message=(
                    f"{len(unreachable)} of {len(checks)} routed LAN subnet(s) did not answer: {details}."
                    if unreachable
                    else f"All {len(checks)} routed private LAN subnet(s) answered via their next hop."
                ),
                cause=(
                    "The router may not route between VLANs/subnets, a firewall may block cross-subnet traffic, "
                    "the route's next hop may be down, or the route may have no adapter behind it."
                    if unreachable
                    else None
                ),
                evidence={"subnets": checks},
                fix_ids=["LAN-03"] if unreachable else [],
                detection_only=bool(unreachable),
            )
        )

    smb_rows = ctx.snapshot.section("smb_client")
    smb_disabled = [
        row for row in smb_rows if str(row.get("EnableSMB2Protocol")).strip().lower() == "false"
    ]
    results.append(
        CheckResult(
            id="LAN-08",
            layer=LAYER,
            status=Status.WARN if smb_disabled else (Status.SKIP if not smb_rows else Status.PASS),
            title="SMB2/3 client",
            message=(
                "The SMB2/3 client protocol is disabled."
                if smb_disabled
                else ("SMB client configuration could not be read." if not smb_rows else "SMB2/3 client is enabled.")
            ),
            cause="Disabling SMB2/3 breaks access to modern shares." if smb_disabled else None,
            evidence={"smb_client": smb_rows},
            fix_ids=["LAN-08"] if smb_disabled else [],
        )
    )

    return results
