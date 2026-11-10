import os
import platform
import re
import subprocess
import time

from modules.network_info import assess_network, get_default_gateway

DEFAULT_TIMEOUT_SECONDS = 20
TRACE_TIMEOUT_SECONDS = 45


def _system():
    return platform.system().lower()


def _is_windows():
    return _system() == "windows"


def _is_macos():
    return _system() == "darwin"


def _creation_flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_elevated():
    try:
        if _is_windows():
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())

        return os.geteuid() == 0

    except (AttributeError, OSError):
        return False


def _powershell(script):
    return [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script,
    ]


def _parse_command(args, display=None):
    return {
        "args": args,
        "display": display or " ".join(args),
    }


def _adapter_commands():
    if _is_windows():
        script = (
            "Get-NetAdapter | Select-Object Name, "
            "InterfaceDescription, Status, LinkSpeed | "
            "Format-Table -AutoSize"
        )

        return [_parse_command(_powershell(script), script)]

    if _is_macos():
        return [_parse_command(["ifconfig"])]

    return [_parse_command(["ip", "-brief", "address"])]


def _ip_config_commands():
    if _is_windows():
        return [_parse_command(["ipconfig", "/all"])]

    if _is_macos():
        return [_parse_command(["ifconfig"])]

    return [_parse_command(["ip", "address"])]


def _ping_args(target, count=4):
    if _is_windows():
        return ["ping", "-n", str(count), target]

    return ["ping", "-c", str(count), target]


def _loopback_commands():
    return [_parse_command(_ping_args("127.0.0.1"))]


def _gateway_commands():
    gateway = get_default_gateway()

    if not gateway:
        return []

    return [_parse_command(_ping_args(gateway))]


def _internet_commands():
    return [_parse_command(_ping_args("1.1.1.1"))]


def _dns_commands():
    return [_parse_command(["nslookup", "www.google.com"])]


def _trace_commands():
    if _is_windows():
        return [
            _parse_command(
                ["tracert", "-d", "-h", "10", "1.1.1.1"]
            )
        ]

    return [
        _parse_command(
            ["traceroute", "-m", "10", "1.1.1.1"]
        )
    ]


def _flush_dns_commands():
    if _is_windows():
        return [_parse_command(["ipconfig", "/flushdns"])]

    if _is_macos():
        return [_parse_command(["dscacheutil", "-flushcache"])]

    return [_parse_command(["resolvectl", "flush-caches"])]


def _renew_commands():
    if not _is_windows():
        return []

    return [
        _parse_command(["ipconfig", "/release"]),
        _parse_command(["ipconfig", "/renew"]),
    ]


def _winsock_commands():
    if not _is_windows():
        return []

    return [_parse_command(["netsh", "winsock", "reset"])]


def _tcpip_commands():
    if not _is_windows():
        return []

    return [_parse_command(["netsh", "int", "ip", "reset"])]


def _definitions():
    windows = _is_windows()

    return [

        {
            "id": "adapter-status",
            "title": "Check network adapters",
            "description": (
                "Confirm that a network adapter is connected "
                "and reporting a link speed."
            ),
            "kind": "check",
            "requires_admin": False,
            "supported": True,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _adapter_commands,
            "reason": None,
        },

        {
            "id": "ip-configuration",
            "title": "Check IP configuration",
            "description": (
                "Review the IP address, subnet mask, default "
                "gateway, and DHCP information for this computer."
            ),
            "kind": "check",
            "requires_admin": False,
            "supported": True,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _ip_config_commands,
            "reason": None,
        },

        {
            "id": "loopback",
            "title": "Test the TCP/IP stack",
            "description": (
                "Ping the loopback address to verify that the "
                "local network stack is responding."
            ),
            "kind": "check",
            "requires_admin": False,
            "supported": True,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _loopback_commands,
            "reason": None,
        },

        {
            "id": "gateway",
            "title": "Ping the default gateway",
            "description": (
                "Test connectivity to the router or gateway that "
                "connects this computer to other networks."
            ),
            "kind": "check",
            "requires_admin": False,
            "supported": True,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _gateway_commands,
            "reason": (
                "No default gateway was detected. Connect to a "
                "network and try again."
            ),
        },

        {
            "id": "internet",
            "title": "Ping the internet",
            "description": (
                "Test connectivity to a public address to see "
                "whether traffic leaves the local network."
            ),
            "kind": "check",
            "requires_admin": False,
            "supported": True,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _internet_commands,
            "reason": None,
        },

        {
            "id": "dns",
            "title": "Test DNS resolution",
            "description": (
                "Resolve a public hostname to confirm that DNS "
                "lookups are working correctly."
            ),
            "kind": "check",
            "requires_admin": False,
            "supported": True,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _dns_commands,
            "reason": None,
        },

        {
            "id": "route-trace",
            "title": "Trace the internet route",
            "description": (
                "Show the first hops toward the internet to spot "
                "where connectivity stops."
            ),
            "kind": "check",
            "requires_admin": False,
            "supported": True,
            "timeout": TRACE_TIMEOUT_SECONDS,
            "command_builder": _trace_commands,
            "reason": None,
        },

        {
            "id": "flush-dns",
            "title": "Flush the DNS cache",
            "description": (
                "Clear cached DNS entries that may be stale or "
                "pointing to the wrong address."
            ),
            "kind": "repair",
            "requires_admin": False,
            "supported": True,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _flush_dns_commands,
            "reason": None,
        },

        {
            "id": "renew-ip",
            "title": "Renew the DHCP lease",
            "description": (
                "Release and request a fresh IP address from the "
                "router. The connection may drop briefly."
            ),
            "kind": "repair",
            "requires_admin": False,
            "supported": windows,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _renew_commands,
            "reason": (
                "Automatic DHCP renewal is only available on "
                "Windows."
            ),
        },

        {
            "id": "reset-winsock",
            "title": "Reset Winsock",
            "description": (
                "Reset the Windows networking catalog. This can "
                "repair broken socket connections, but requires a "
                "restart afterwards."
            ),
            "kind": "repair",
            "requires_admin": True,
            "supported": windows,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _winsock_commands,
            "reason": (
                "Resetting Winsock is only available on Windows."
            ),
        },

        {
            "id": "reset-tcpip",
            "title": "Reset the TCP/IP stack",
            "description": (
                "Reset the Windows IP stack to its default state. "
                "This is a stronger repair and requires a restart "
                "afterwards."
            ),
            "kind": "repair",
            "requires_admin": True,
            "supported": windows,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "command_builder": _tcpip_commands,
            "reason": (
                "Resetting the TCP/IP stack is only available on "
                "Windows."
            ),
        },

    ]


def _serialize_step(step):
    commands = step["command_builder"]()

    available = bool(commands) and step["supported"]

    return {
        "id": step["id"],
        "title": step["title"],
        "description": step["description"],
        "kind": step["kind"],
        "requires_admin": step["requires_admin"],
        "supported": step["supported"],
        "available": available,
        "command": (
            " && ".join(
                item["display"] for item in commands
            )
            if commands
            else "Unavailable"
        ),
        "reason": step.get("reason"),
        "timeout": step["timeout"],
    }


def list_diagnostics():
    steps = [
        _serialize_step(step)
        for step in _definitions()
    ]

    return {
        "system": platform.system(),
        "elevated": is_elevated(),
        "steps": steps,
        "check_count": sum(
            1 for step in steps
            if step["kind"] == "check"
        ),
        "repair_count": sum(
            1 for step in steps
            if step["kind"] == "repair"
        ),
    }


def _result(step_id, success, commands, output, duration_ms, reason=None):
    result = {
        "id": step_id,
        "success": success,
        "commands": commands,
        "output": output,
        "duration_ms": duration_ms,
    }

    if reason:
        result["reason"] = reason

    return result


def _diagnose_gateway_failure():
    gateway = get_default_gateway()
    diagnosis = assess_network(gateway=gateway)
    issues = diagnosis.get("issues") or []

    for issue in issues:
        if issue.get("id") == "network-down" and issue.get("message"):
            return issue["message"]

    if not gateway:
        return (
            "Network is down or disconnected: no default gateway was detected. "
            "Connect to a network and try again."
        )

    for issue in issues:
        if issue.get("id") == "wrong-gateway-subnet":
            return (
                issue["message"]
                + " The gateway ping failed, which also suggests the "
                "configured gateway is wrong or unreachable."
            )

    return (
        f"Default gateway {gateway} did not respond. The router may be "
        "offline, unreachable, or blocking ping requests. If the gateway "
        "address looks unfamiliar, it may be configured incorrectly."
    )


def _diagnose_ip_configuration(output, command_success):
    diagnosis = assess_network()
    issues = diagnosis.get("issues") or []
    output_text = output or ""

    for issue in issues:
        if issue.get("id") == "network-down" and issue.get("message"):
            return False, issue["message"]

    apipa_match = re.search(r"\b169\.254\.\d{1,3}\.\d{1,3}\b", output_text)
    if apipa_match or any(issue.get("id") == "apipa-address" for issue in issues):
        address = apipa_match.group(0) if apipa_match else "169.254.x.x"
        return (
            False,
            f"IP configuration shows an automatic private address ({address}). "
            "This usually means DHCP did not assign an address. Check the "
            "router/DHCP server or run the DHCP lease renewal repair."
        )

    for issue in issues:
        if issue.get("id") == "wrong-gateway-subnet":
            return False, issue["message"]
        if issue.get("id") == "missing-gateway":
            return (
                False,
                "No default gateway is configured. This computer may not be "
                "able to reach other networks or the internet."
            )

    if not command_success:
        return (
            False,
            "The IP configuration command failed. Check the command output "
            "for details."
        )

    return True, None


def _diagnose_dns_failure():
    diagnosis = assess_network()
    gateway = get_default_gateway()
    parts = [
        "DNS resolution failed. The configured DNS server may be unreachable, "
        "incorrect, or blocked."
    ]

    if any((issue.get("id") == "apipa-address") for issue in diagnosis.get("issues") or []):
        parts.append(
            "This computer also appears to have a DHCP/APIPA address problem, "
            "which can prevent DNS from working."
        )
    elif gateway and diagnosis.get("gateway_in_subnet") is False:
        parts.append(
            "The default gateway also appears to be misconfigured, which can "
            "prevent access to DNS servers."
        )

    return " ".join(parts)


def _diagnose_internet_failure():
    diagnosis = assess_network()
    gateway = get_default_gateway()
    issues = diagnosis.get("issues") or []

    for issue in issues:
        if issue.get("id") == "network-down" and issue.get("message"):
            return issue["message"]

    if not gateway:
        return (
            "Network is down or disconnected: the internet is unreachable "
            "because no default gateway was detected."
        )

    if diagnosis.get("gateway_in_subnet") is False:
        return (
            "The internet is unreachable and the default gateway appears to be "
            "configured incorrectly (wrong subnet). Check the gateway address "
            "in your IP configuration."
        )

    return (
        "The internet is unreachable from this computer. The problem may be "
        "with the default gateway, router internet connection, ISP, firewall, "
        "or upstream routing."
    )


def _diagnose_loopback_failure():
    return (
        "The local network stack (loopback) test failed. This points to a "
        "problem with TCP/IP on this computer. Restarting, renewing the "
        "network, or resetting Winsock/TCP-IP may help."
    )


def _diagnose_adapter_status(command_success):
    if not command_success:
        return (
            "Could not read network adapter status. Check the command output "
            "for details."
        )

    return None


def _diagnose_runtime(step_id, output, success):
    if step_id == "adapter-status":
        return _diagnose_adapter_status(success)

    if success:
        return None

    if step_id == "ip-configuration":
        _, reason = _diagnose_ip_configuration(output, success)
        return reason

    if step_id == "loopback":
        return _diagnose_loopback_failure()

    if step_id == "gateway":
        return _diagnose_gateway_failure()

    if step_id == "internet":
        return _diagnose_internet_failure()

    if step_id == "dns":
        return _diagnose_dns_failure()

    if step_id == "route-trace":
        return (
            "The route trace did not complete successfully. This can indicate "
            "where traffic stops between this computer and the internet."
        )

    if step_id in {"flush-dns", "renew-ip", "reset-winsock", "reset-tcpip"}:
        if not is_elevated() and step_id in {"reset-winsock", "reset-tcpip"}:
            return (
                "This repair did not complete successfully. It requires "
                "administrator rights; try running NetScope as administrator."
            )
        return "The repair did not complete successfully. Check the command output for details."

    return "This step reported a problem. Check the command output for details."


def run_diagnostic(step_id):
    step = next(
        (
            item for item in _definitions()
            if item["id"] == step_id
        ),
        None,
    )

    if step is None:
        raise KeyError(step_id)

    if not step["supported"]:
        reason = step.get("reason") or "This step is not supported."
        return _result(
            step_id,
            False,
            [],
            reason,
            0,
            reason=reason,
        )

    commands = step["command_builder"]()

    if not commands:
        reason = (
            step.get("reason")
            or "This step is not available right now."
        )
        return _result(
            step_id,
            False,
            [],
            reason,
            0,
            reason=reason,
        )

    started = time.monotonic()

    chunks = []
    success = True

    for item in commands:

        chunks.append(f"> {item['display']}")

        try:
            completed = subprocess.run(
                item["args"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=step["timeout"],
                creationflags=_creation_flags(),
            )

        except subprocess.TimeoutExpired:
            success = False

            chunks.append(
                f"[timed out after {step['timeout']} seconds]"
            )

            chunks.append("")

            continue

        except (OSError, subprocess.SubprocessError) as error:
            success = False

            chunks.append(
                f"[could not run command: {error}]"
            )

            chunks.append("")

            continue

        output = (
            (completed.stdout or "")
            + (completed.stderr or "")
        ).strip()

        if output:
            chunks.append(output)

        if completed.returncode != 0:
            success = False

            chunks.append(
                f"[exit code {completed.returncode}]"
            )

        chunks.append("")

    duration_ms = int(
        (time.monotonic() - started) * 1000
    )

    output = "\n".join(chunks).strip()

    if step_id == "ip-configuration":
        success, config_reason = _diagnose_ip_configuration(output, success)
        if config_reason:
            return _result(
                step_id,
                success,
                [item["display"] for item in commands],
                output,
                duration_ms,
                reason=config_reason,
            )

    reason = _diagnose_runtime(step_id, output, success)

    return _result(
        step_id,
        success,
        [item["display"] for item in commands],
        output,
        duration_ms,
        reason=reason,
    )
