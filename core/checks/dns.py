"""DNS / name-resolution checks (DNS-01 .. DNS-03)."""

from __future__ import annotations

from pathlib import Path

from core.checks.context import CheckContext, configured_dns_servers, skipped, text
from core.models import CheckResult, Layer, Status

LAYER = Layer.DNS

TEST_NAME = "www.msftconnecttest.com"
PUBLIC_SERVERS = ("1.1.1.1", "8.8.8.8")

_BLOCKING_ADDRESSES = {"0.0.0.0", "127.0.0.1", "::1"}


def _default_hosts_path() -> Path:
    system_root = __import__("os").environ.get("SystemRoot", r"C:\Windows")
    return Path(system_root) / "System32" / "drivers" / "etc" / "hosts"


def _hosts_overrides(path: Path) -> list[dict[str, str]]:
    overrides: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return overrides

    for line in lines:
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        address, hostname = parts[0], parts[1]
        if address in _BLOCKING_ADDRESSES or hostname.lower() == TEST_NAME:
            overrides.append({"address": address, "hostname": hostname})
    return overrides


def run(ctx: CheckContext) -> list[CheckResult]:
    if not ctx.is_windows:
        return [skipped(LAYER, "DNS-02", "DNS", "Windows-only check")]

    servers = configured_dns_servers(ctx.snapshot)
    if not servers:
        return [
            CheckResult(
                id="DNS-02",
                layer=LAYER,
                status=Status.FAIL,
                title="DNS servers configured",
                message="No IPv4 DNS server is configured on any adapter.",
                cause="DNS resolution cannot work without a resolver.",
                evidence={"servers": []},
                fix_ids=["DNS-02"],
            )
        ]

    configured = [ctx.probe.dns_query(TEST_NAME, server) for server in servers]
    public = [ctx.probe.dns_query(TEST_NAME, server) for server in PUBLIC_SERVERS]
    configured_ok = [answer for answer in configured if answer.ok]
    public_ok = [answer for answer in public if answer.ok]

    evidence = {
        "test_name": TEST_NAME,
        "configured": [
            {
                "server": answer.server,
                "ok": answer.ok,
                "addresses": answer.addresses,
                "latency_ms": answer.latency_ms,
                "rcode": answer.rcode,
                "error": answer.error,
            }
            for answer in configured
        ],
        "public": [
            {
                "server": answer.server,
                "ok": answer.ok,
                "addresses": answer.addresses,
                "latency_ms": answer.latency_ms,
                "rcode": answer.rcode,
                "error": answer.error,
            }
            for answer in public
        ],
    }

    results: list[CheckResult] = []

    if configured_ok:
        results.append(
            CheckResult(
                id="DNS-02",
                layer=LAYER,
                status=Status.PASS,
                title="DNS resolution",
                message=f"Configured DNS server(s) resolved {TEST_NAME}.",
                evidence=evidence,
            )
        )
    elif public_ok:
        results.append(
            CheckResult(
                id="DNS-02",
                layer=LAYER,
                status=Status.FAIL,
                title="Configured DNS server failing",
                message=(
                    f"Configured resolver(s) {', '.join(servers)} failed, but a public "
                    f"resolver answered {TEST_NAME}."
                ),
                cause="The DNS servers configured on this adapter are unreachable or broken.",
                evidence=evidence,
                fix_ids=["DNS-01", "DNS-02"],
            )
        )
    else:
        results.append(
            CheckResult(
                id="DNS-02",
                layer=LAYER,
                status=Status.FAIL,
                title="DNS resolution failing everywhere",
                message=(
                    f"Neither the configured resolver(s) nor public resolvers could resolve {TEST_NAME}."
                ),
                cause=(
                    "Port 53 may be filtered, a captive portal may be blocking traffic, "
                    "or the upstream resolver/ISP is failing."
                ),
                evidence=evidence,
                fix_ids=["DNS-01", "DNS-02"],
                detection_only=True,
            )
        )

    system = ctx.probe.resolve(TEST_NAME)
    if public_ok and not system.ok:
        results.append(
            CheckResult(
                id="DNS-01",
                layer=LAYER,
                status=Status.WARN,
                title="System resolver differs from direct DNS",
                message=(
                    "A direct query works but the Windows resolver fails, suggesting a stale "
                    "cache or a local override."
                ),
                cause="Windows DNS cache or a local override is returning the wrong result.",
                evidence={
                    "system": {"ok": system.ok, "addresses": system.addresses, "error": system.error},
                    "public": evidence["public"],
                },
                fix_ids=["DNS-01", "DNS-03"],
            )
        )
    else:
        results.append(
            CheckResult(
                id="DNS-01",
                layer=LAYER,
                status=Status.PASS,
                title="Windows resolver",
                message=(
                    "Windows resolver agrees with direct DNS."
                    if system.ok
                    else "Direct DNS also fails; this is not just a stale local cache."
                ),
                evidence={"system_ok": system.ok},
            )
        )

    hosts_path = ctx.hosts_path or _default_hosts_path()
    overrides = _hosts_overrides(hosts_path)
    results.append(
        CheckResult(
            id="DNS-03",
            layer=LAYER,
            status=Status.WARN if overrides else Status.PASS,
            title="Hosts file overrides",
            message=(
                f"{len(overrides)} blocking/override entries found in the hosts file."
                if overrides
                else "No blocking hosts-file entries found."
            ),
            cause=(
                "Leftover blocklists, malware or old development entries can override DNS."
                if overrides
                else None
            ),
            evidence={"path": str(hosts_path), "overrides": overrides[:20]},
            fix_ids=["DNS-03"] if overrides else [],
        )
    )

    return results
