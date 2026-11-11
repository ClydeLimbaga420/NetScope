import ipaddress
import socket
import psutil
import platform
import re
import subprocess


def _same_subnet(ip, gateway, netmask):
    if not ip or not gateway or not netmask:
        return None

    try:
        network = ipaddress.IPv4Network(
            f"{ip}/{netmask}",
            strict=False,
        )
        return ipaddress.IPv4Address(gateway) in network
    except (ipaddress.AddressValueError, ValueError):
        return None


def _active_ipv4_interfaces():
    interfaces = []
    stats = psutil.net_if_stats()
    addresses = psutil.net_if_addrs()

    for name, addrs in addresses.items():
        ipv4 = next(
            (a for a in addrs if a.family == socket.AF_INET),
            None,
        )
        mac = next(
            (
                a.address
                for a in addrs
                if getattr(a.family, "name", "") == "AF_LINK"
                or str(a.family) == "-1"
            ),
            None,
        )

        if not ipv4 or ipv4.address.startswith("127."):
            continue

        status = stats.get(name)
        netmask = getattr(ipv4, "netmask", None)

        interfaces.append({
            "name": name,
            "ipv4": ipv4.address,
            "netmask": netmask,
            "mac": mac,
            "is_up": bool(status.isup) if status else False,
            "speed_mbps": (
                status.speed
                if status and status.speed > 0
                else None
            ),
        })

    return interfaces


def _windows_default_gateway(output):
    lines = output.splitlines()

    for index, line in enumerate(lines):
        match = re.search(
            r"Default Gateway[ .]*:\s*(.*)$",
            line,
            re.I,
        )

        if not match:
            continue

        candidates = []

        if match.group(1).strip():
            candidates.append(match.group(1).strip())

        for follow in lines[index + 1:index + 4]:
            if not follow.strip() or ":" in follow:
                break
            candidates.append(follow.strip())

        for candidate in candidates:
            ipv4 = re.search(
                r"\b(\d{1,3}(?:\.\d{1,3}){3})\b",
                candidate,
            )

            if ipv4 and ipv4.group(1) != "0.0.0.0":
                return ipv4.group(1)

    return None


def get_default_gateway():

    system = platform.system().lower()

    try:

        if system == "windows":

            output = subprocess.check_output(
                ["ipconfig"],
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0
                )
            )

            return _windows_default_gateway(output)

        elif system == "linux":

            output = subprocess.check_output(
                ["ip", "route", "show", "default"],
                text=True
            )

            match = re.search(
                r"default via ([0-9.]+)",
                output
            )

            return match.group(1) if match else None

        elif system == "darwin":

            output = subprocess.check_output(
                ["route", "-n", "get", "default"],
                text=True
            )

            match = re.search(
                r"gateway:\s*([0-9.]+)",
                output
            )

            return match.group(1) if match else None

    except (OSError, subprocess.SubprocessError):
        pass

    return None


def assess_network(gateway=None, interfaces=None):
    if interfaces is None:
        interfaces = _active_ipv4_interfaces()

    if gateway is None:
        gateway = get_default_gateway()

    issues = []
    up_interfaces = [item for item in interfaces if item.get("is_up")]
    candidate_interfaces = up_interfaces or interfaces
    network_down = False

    if not interfaces:
        network_down = True
        issues.append({
            "id": "network-down",
            "severity": "error",
            "message": (
                "Network is down: no active network adapters with an IPv4 "
                "address were detected. Check your Ethernet/Wi-Fi connection "
                "and make sure the adapter is enabled."
            ),
        })
    elif not up_interfaces:
        network_down = True
        issues.append({
            "id": "network-down",
            "severity": "error",
            "message": (
                "Network is down: no network adapter is currently connected. "
                "Check your Ethernet/Wi-Fi connection or enable the network "
                "adapter."
            ),
        })

    apipa = [
        item for item in candidate_interfaces
        if (item.get("ipv4") or "").startswith("169.254.")
    ]
    if apipa:
        sample = apipa[0]["ipv4"]
        issues.append({
            "id": "apipa-address",
            "severity": "error",
            "message": (
                f"This computer is using an automatic private IP address "
                f"({sample}). This usually means it could not get an IP "
                "address from DHCP. Check the network/router or renew the "
                "DHCP lease."
            ),
        })

    if not gateway:
        issues.append({
            "id": "missing-gateway",
            "severity": "warning",
            "message": (
                "No default gateway was detected. You may be disconnected, "
                "or the network adapter is not configured with a gateway."
            ),
        })
        return {
            "gateway": gateway,
            "issues": issues,
            "gateway_in_subnet": None,
            "network_down": network_down,
        }

    subnet_matches = []
    for item in candidate_interfaces:
        match = _same_subnet(
            item.get("ipv4"),
            gateway,
            item.get("netmask"),
        )
        if match is True:
            subnet_matches.append(item)

    comparable = [
        item for item in candidate_interfaces
        if item.get("ipv4") and item.get("netmask")
    ]
    gateway_in_subnet = bool(subnet_matches) if comparable else None

    if gateway_in_subnet is False:
        sample = comparable[0]
        issues.append({
            "id": "wrong-gateway-subnet",
            "severity": "error",
            "message": (
                f"Default gateway {gateway} is not in the same subnet as "
                f"{sample['ipv4']} ({sample.get('netmask')}) on "
                f"{sample['name']}. The default gateway may be configured "
                "incorrectly."
            ),
        })

    return {
        "gateway": gateway,
        "issues": issues,
        "gateway_in_subnet": gateway_in_subnet,
        "network_down": network_down,
    }


def get_network_info():
    interfaces = _active_ipv4_interfaces()

    hostname = socket.gethostname()

    try:
        local_ip = socket.gethostbyname(hostname)
    except OSError:
        local_ip = None

    gateway = get_default_gateway()
    diagnosis = assess_network(gateway=gateway, interfaces=interfaces)

    public_interfaces = [
        {
            "name": item["name"],
            "ipv4": item["ipv4"],
            "mac": item["mac"],
            "is_up": item["is_up"],
            "speed_mbps": item["speed_mbps"],
        }
        for item in interfaces
    ]

    return {
        "hostname": hostname,
        "local_ip": local_ip,
        "gateway": gateway,
        "interfaces": public_interfaces,
        "interface_count": len(public_interfaces),
        "diagnosis": diagnosis,
    }