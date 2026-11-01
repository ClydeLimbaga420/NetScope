import socket
import psutil
import platform
import re
import subprocess


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

            gateways = re.findall(
                r"Default Gateway[ .]*:\s*([0-9.]+)",
                output,
                re.I
            )

            return next(
                (g for g in gateways if g and g != "0.0.0.0"),
                None
            )

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


def get_network_info():

    interfaces = []

    stats = psutil.net_if_stats()
    addresses = psutil.net_if_addrs()

    for name, addrs in addresses.items():

        ipv4 = next(
            (
                a.address
                for a in addrs
                if a.family == socket.AF_INET
            ),
            None
        )

        mac = next(
            (
                a.address
                for a in addrs
                if getattr(a.family, "name", "") == "AF_LINK"
                or str(a.family) == "-1"
            ),
            None
        )

        if ipv4 and not ipv4.startswith("127."):

            status = stats.get(name)

            interfaces.append({
                "name": name,
                "ipv4": ipv4,
                "mac": mac,
                "is_up": bool(status.isup) if status else False,
                "speed_mbps": (
                    status.speed
                    if status and status.speed > 0
                    else None
                )
            })

    hostname = socket.gethostname()

    try:
        local_ip = socket.gethostbyname(hostname)
    except OSError:
        local_ip = None

    return {
        "hostname": hostname,
        "local_ip": local_ip,
        "gateway": get_default_gateway(),
        "interfaces": interfaces,
        "interface_count": len(interfaces)
    }