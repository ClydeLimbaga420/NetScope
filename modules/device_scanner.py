import ipaddress
import platform
import re
import socket
import struct
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

import psutil

from modules.oui_vendors import OUI_VENDORS


NAME_CACHE_TTL_SECONDS = 300
NAME_CACHE_MISS_TTL_SECONDS = 60
NAME_RESOLVE_TIMEOUT_SECONDS = 1.5
NAME_CACHE = {}
NAME_CACHE_LOCK = threading.Lock()
NAME_IN_FLIGHT = set()
MISSING = object()

SCAN_CACHE_SECONDS = 15
SCAN_MAX_HOSTS = 1024
SCAN_PORT = 33434
SCAN_SETTLE_SECONDS = 0.5
SCAN_LOCK = threading.Lock()
LAST_SCAN = 0.0

WIFI_INTERFACE_HINTS = ("wi-fi", "wifi", "wireless", "wlan", "802.11")

WIRELESS_VENDOR_HINTS = (
    "apple",
    "samsung",
    "xiaomi",
    "huawei",
    "honor",
    "oneplus",
    "oppo",
    "vivo",
    "realme",
    "google",
    "motorola",
    "lg electronics",
    "nintendo",
    "amazon",
    "roku",
    "sonos",
    "espressif",
    "tuya",
    "ring llc",
    "nest labs",
    "tcl",
    "hisense",
    "vizio",
    "nothing technology",
)

INTERFACE_LINE = re.compile(
    r"([0-9]{1,3}(?:\.[0-9]{1,3}){3})\s+---\s+0x[0-9a-fA-F]+"
)


def _creation_flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _is_usable_host(ip):
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False

    return (
        address.version == 4
        and not address.is_multicast
        and not address.is_loopback
        and not address.is_unspecified
        and str(address) != "255.255.255.255"
        and not ip.endswith(".255")
    )


def _clean_name(name, ip):
    name = (name or "").strip().rstrip(".")

    if not name or name == ip or re.fullmatch(r"[\d.]+", name):
        return None

    return name


def _cached_name(ip):
    with NAME_CACHE_LOCK:
        entry = NAME_CACHE.get(ip)

    if entry is None:
        return MISSING

    timestamp, name = entry

    ttl = (
        NAME_CACHE_TTL_SECONDS
        if name
        else NAME_CACHE_MISS_TTL_SECONDS
    )

    if time.monotonic() - timestamp > ttl:
        return MISSING

    return name


def _store_name(ip, name):
    with NAME_CACHE_LOCK:
        NAME_CACHE[ip] = (time.monotonic(), name)


def _reverse_dns_name(ip):
    try:
        name = socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror, socket.gaierror):
        return None

    return _clean_name(name, ip)


def _skip_dns_name(data, offset):
    while offset < len(data):
        length = data[offset]

        if length == 0:
            return offset + 1

        if length & 0xC0 == 0xC0:
            return offset + 2

        offset += 1 + length

    return offset


def _netbios_name(ip):
    encoded = bytearray()

    for byte in b"*" + b"\x00" * 15:
        encoded.append(ord("A") + (byte >> 4))
        encoded.append(ord("A") + (byte & 0x0F))

    packet = (
        struct.pack(">HHHHHH", 0x4E42, 0, 1, 0, 0, 0)
        + b"\x20"
        + bytes(encoded)
        + b"\x00"
        + struct.pack(">HH", 0x0021, 0x0001)
    )

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.4)
            sock.sendto(packet, (ip, 137))
            data, address = sock.recvfrom(2048)
    except OSError:
        return None

    if address[0] != ip or len(data) < 12:
        return None

    ancount = struct.unpack(">H", data[6:8])[0]

    if ancount < 1:
        return None

    offset = _skip_dns_name(data, 12) + 4

    for _ in range(ancount):
        offset = _skip_dns_name(data, offset)

        if offset + 10 > len(data):
            break

        rtype, _, _, rdlength = struct.unpack(
            ">HHIH",
            data[offset:offset + 10]
        )

        offset += 10

        rdata = data[offset:offset + rdlength]
        offset += rdlength

        if rtype != 0x0021 or not rdata:
            continue

        count = rdata[0]

        for index in range(count):
            start = 1 + index * 18
            entry = rdata[start:start + 18]

            if len(entry) < 18:
                break

            suffix = entry[15]
            flags = struct.unpack(">H", entry[16:18])[0]

            if suffix != 0x00 or flags & 0x8000:
                continue

            name = (
                entry[:15]
                .decode("ascii", errors="ignore")
                .strip("\x00 ")
            )

            name = _clean_name(name, ip)

            if name:
                return name

    return None


def _resolve_name(ip):
    return _netbios_name(ip) or _reverse_dns_name(ip)


def _resolve_and_cache(ip):
    name = None

    try:
        name = _resolve_name(ip)
    except Exception:
        name = None
    finally:
        _store_name(ip, name)

        with NAME_CACHE_LOCK:
            NAME_IN_FLIGHT.discard(ip)

    return name


def _resolve_names(devices):
    pending = []

    for device in devices:
        if device.get("name"):
            continue

        cached = _cached_name(device["ip"])

        if cached is MISSING:
            with NAME_CACHE_LOCK:
                if device["ip"] in NAME_IN_FLIGHT:
                    device["name"] = None
                    continue

                NAME_IN_FLIGHT.add(device["ip"])

            pending.append(device)
        else:
            device["name"] = cached

    if not pending:
        return

    executor = ThreadPoolExecutor(
        max_workers=min(10, len(pending))
    )

    futures = {
        executor.submit(_resolve_and_cache, device["ip"]): device
        for device in pending
    }

    done, not_done = wait(
        futures,
        timeout=NAME_RESOLVE_TIMEOUT_SECONDS
    )

    for future in done:
        device = futures[future]

        try:
            device["name"] = future.result()
        except Exception:
            device["name"] = None

    for future in not_done:
        device = futures[future]

        device["name"] = None

        if future.cancel():
            with NAME_CACHE_LOCK:
                NAME_IN_FLIGHT.discard(device["ip"])

    executor.shutdown(wait=False, cancel_futures=True)


def _local_ipv4_targets():
    try:
        addresses = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception:
        return []

    networks = {}
    own_ips = set()

    for name, interface_addresses in addresses.items():
        interface = stats.get(name)

        if interface is not None and not interface.isup:
            continue

        for address in interface_addresses:
            if address.family != socket.AF_INET:
                continue

            if not address.address or not address.netmask:
                continue

            try:
                network = ipaddress.ip_network(
                    f"{address.address}/{address.netmask}",
                    strict=False
                )
            except ValueError:
                continue

            if (
                network.version != 4
                or network.is_loopback
                or network.is_link_local
                or not network.is_private
            ):
                continue

            own_ips.add(address.address)

            if network.num_addresses > SCAN_MAX_HOSTS + 2:
                network = ipaddress.ip_network(
                    f"{address.address}/24",
                    strict=False
                )

            networks[str(network)] = network

    targets = []

    for network in networks.values():
        for host in network.hosts():
            ip = str(host)

            if ip in own_ips:
                continue

            targets.append(ip)

            if len(targets) >= SCAN_MAX_HOSTS:
                return targets

    return targets


def _warm_arp_cache():
    global LAST_SCAN

    with SCAN_LOCK:
        now = time.monotonic()

        if now - LAST_SCAN < SCAN_CACHE_SECONDS:
            return

        LAST_SCAN = now

        targets = _local_ipv4_targets()

        if not targets:
            return

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError:
            return

        try:
            for ip in targets:
                try:
                    sock.sendto(b"", (ip, SCAN_PORT))
                except OSError:
                    pass
        finally:
            sock.close()

        time.sleep(SCAN_SETTLE_SECONDS)


def _is_locally_administered_mac(mac):
    try:
        first_octet = int(mac.split(":")[0], 16)
    except (ValueError, IndexError):
        return False

    return bool(first_octet & 0x02)


def _vendor_for_mac(mac):
    if _is_locally_administered_mac(mac):
        return "Private MAC"

    prefix = mac.replace(":", "").replace("-", "").upper()[:6]

    return OUI_VENDORS.get(prefix)


def _add_vendors(devices):
    for device in devices:
        device["vendor"] = _vendor_for_mac(device["mac"])


def _normalize_mac(mac):
    return (mac or "").replace("-", ":").lower()


def _is_wireless_interface(name):
    haystack = (name or "").lower()

    return any(hint in haystack for hint in WIFI_INTERFACE_HINTS)


def _is_wireless_vendor(vendor):
    haystack = (vendor or "").lower()

    return any(hint in haystack for hint in WIRELESS_VENDOR_HINTS)


def _local_context():
    context = {
        "own_ips": set(),
        "own_macs": set(),
        "interfaces": {}
    }

    try:
        addresses = psutil.net_if_addrs()
    except Exception:
        return context

    for name, interface_addresses in addresses.items():
        wireless = _is_wireless_interface(name)

        for address in interface_addresses:
            if address.family == socket.AF_INET and address.address:
                context["own_ips"].add(address.address)
                context["interfaces"][address.address] = {
                    "name": name,
                    "wireless": wireless
                }

            family_name = getattr(address.family, "name", "")

            if (
                family_name == "AF_LINK"
                or str(address.family) == "-1"
            ):
                mac = _normalize_mac(address.address)

                if mac and mac != "??:??:??:??:??:??":
                    context["own_macs"].add(mac)

    return context


def _default_gateway():
    try:
        from modules.network_info import get_default_gateway

        gateway = get_default_gateway()

        if gateway:
            return gateway
    except Exception:
        pass

    if platform.system().lower() != "windows":
        return None

    try:
        result = subprocess.run(
            ["route", "print", "-4"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=_creation_flags()
        )
    except (OSError, subprocess.SubprocessError):
        return None

    return _parse_route_gateway(result.stdout)


def _parse_route_gateway(output):
    match = re.search(
        r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+"
        r"([0-9]{1,3}(?:\.[0-9]{1,3}){3})",
        output,
        re.MULTILINE
    )

    if not match:
        return None

    gateway = match.group(1)

    return None if gateway == "0.0.0.0" else gateway


def _classify_connection(device, context, gateway):
    ip = device.get("ip")
    mac = _normalize_mac(device.get("mac"))
    interface = context["interfaces"].get(device.get("interface_ip"))

    if ip in context["own_ips"] or (mac and mac in context["own_macs"]):
        return "This PC", "Address belongs to a local adapter"

    if gateway and ip == gateway:
        return "Router", "Default gateway of this PC"

    if interface and interface["wireless"]:
        return "Wireless", "Reached through the Wi-Fi adapter"

    if mac and _is_locally_administered_mac(mac):
        return "Wireless", "Randomized (private) MAC, typical of Wi-Fi devices"

    if _is_wireless_vendor(device.get("vendor")):
        return "Wireless", "Mobile or IoT vendor commonly seen on Wi-Fi"

    if interface and not interface["wireless"]:
        return "Wired", "Reached through an Ethernet adapter"

    return "Unknown", "Connection type could not be determined"


def _add_connections(devices):
    context = _local_context()
    gateway = _default_gateway()

    for device in devices:
        label, detail = _classify_connection(device, context, gateway)
        device["connection"] = label
        device["connection_detail"] = detail


def _parse_windows(output, devices, seen):
    pattern = r"^\s*([0-9.]+)\s+([0-9a-fA-F-]{17})\s+(\w+)"
    interface_ip = None

    for line in output.splitlines():
        header = INTERFACE_LINE.search(line)

        if header:
            interface_ip = header.group(1)
            continue

        match = re.match(pattern, line)

        if not match:
            continue

        ip, mac, kind = match.groups()

        if ip in seen or not _is_usable_host(ip):
            continue

        seen.add(ip)

        devices.append({
            "name": None,
            "ip": ip,
            "mac": mac.replace("-", ":").lower(),
            "type": kind,
            "vendor": None,
            "interface_ip": interface_ip
        })


def _parse_unix(output, devices, seen):
    pattern = (
        r"^(?P<name>\S+)?\s*"
        r"\((?P<ip>[\d.]+)\)\s+"
        r"at\s+(?P<mac>[0-9a-fA-F:]+)"
    )

    for line in output.splitlines():
        match = re.match(pattern, line)

        if not match:
            continue

        ip = match.group("ip")

        if ip in seen or not _is_usable_host(ip):
            continue

        seen.add(ip)

        devices.append({
            "name": _clean_name(match.group("name"), ip),
            "ip": ip,
            "mac": match.group("mac").lower(),
            "type": "arp",
            "vendor": None,
            "interface_ip": None
        })


def get_arp_devices():
    _warm_arp_cache()

    try:
        result = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=_creation_flags()
        )

        output = result.stdout

    except (OSError, subprocess.SubprocessError):
        return []

    devices = []
    seen = set()

    if platform.system().lower() == "windows":
        _parse_windows(output, devices, seen)
    else:
        _parse_unix(output, devices, seen)

    _add_vendors(devices)

    _add_connections(devices)

    _resolve_names(devices)

    return sorted(
        devices,
        key=lambda item: tuple(
            int(part) for part in item["ip"].split(".")
        )
    )
