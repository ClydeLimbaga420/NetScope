import modules.device_scanner as scanner


def _device(**overrides):
    device = {
        "ip": "192.168.1.20",
        "mac": "3c:22:fb:aa:bb:cc",
        "vendor": None,
        "interface_ip": None,
    }
    device.update(overrides)
    return device


def _context(interfaces=None, own_ips=None, own_macs=None):
    return {
        "own_ips": set(own_ips or []),
        "own_macs": set(own_macs or []),
        "interfaces": dict(interfaces or {}),
    }


def test_parse_windows_tracks_interface_for_each_entry():
    output = """
Interface: 192.168.1.10 --- 0x8
  Internet Address      Physical Address      Type
  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic
  192.168.1.21          11-22-33-44-55-66     dynamic

Interface: 10.0.0.5 --- 0x9
  Internet Address      Physical Address      Type
  10.0.0.7              77-88-99-aa-bb-cc     dynamic
"""

    devices = []
    scanner._parse_windows(output, devices, set())

    assert [device["ip"] for device in devices] == [
        "192.168.1.1",
        "192.168.1.21",
        "10.0.0.7",
    ]
    assert [device["interface_ip"] for device in devices] == [
        "192.168.1.10",
        "192.168.1.10",
        "10.0.0.5",
    ]
    assert devices[0]["mac"] == "aa:bb:cc:dd:ee:ff"


def test_classify_this_pc_before_router():
    context = _context(
        interfaces={"192.168.1.10": {"name": "Wi-Fi", "wireless": True}},
        own_ips=["192.168.1.10"],
        own_macs=["aa:bb:cc:dd:ee:ff"],
    )

    assert scanner._classify_connection(
        _device(ip="192.168.1.10"), context, "192.168.1.1"
    )[0] == "This PC"

    assert scanner._classify_connection(
        _device(ip="192.168.1.1"), context, "192.168.1.1"
    )[0] == "Router"


def test_classify_wireless_when_seen_on_wifi_adapter():
    context = _context(
        interfaces={"192.168.1.10": {"name": "Wi-Fi", "wireless": True}}
    )
    device = _device(interface_ip="192.168.1.10")

    label, detail = scanner._classify_connection(device, context, None)

    assert label == "Wireless"
    assert "Wi-Fi" in detail


def test_classify_private_mac_as_wireless():
    device = _device(mac="02:11:22:33:44:55")

    assert scanner._classify_connection(
        device, _context(), None
    )[0] == "Wireless"


def test_classify_mobile_vendor_as_wireless():
    device = _device(vendor="Apple, Inc.")

    assert scanner._classify_connection(
        device, _context(), None
    )[0] == "Wireless"


def test_classify_wired_when_seen_on_ethernet_adapter():
    context = _context(
        interfaces={"192.168.1.10": {"name": "Ethernet", "wireless": False}}
    )
    device = _device(interface_ip="192.168.1.10", vendor="Dell Inc.")

    assert scanner._classify_connection(
        device, context, None
    )[0] == "Wired"


def test_classify_unknown_without_interface_hints():
    assert scanner._classify_connection(
        _device(vendor="Acme Corp."), _context(), None
    )[0] == "Unknown"


def test_is_wireless_interface_hints():
    assert scanner._is_wireless_interface("Wi-Fi 2")
    assert scanner._is_wireless_interface("WLAN")
    assert not scanner._is_wireless_interface("Ethernet")


def test_parse_route_gateway_reads_ipv4_default_route():
    output = """
===========================================================================
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0    192.168.254.254    192.168.254.196     25
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
"""

    assert scanner._parse_route_gateway(output) == "192.168.254.254"


def test_parse_route_gateway_returns_none_without_default_route():
    assert scanner._parse_route_gateway("no routes here") is None


def test_add_connections_sets_label_and_detail(monkeypatch):
    monkeypatch.setattr(
        scanner,
        "_local_context",
        lambda: _context(
            interfaces={"192.168.1.10": {"name": "Wi-Fi", "wireless": True}}
        ),
    )
    monkeypatch.setattr(scanner, "_default_gateway", lambda: "192.168.1.1")

    devices = [
        _device(ip="192.168.1.1", mac="aa:aa:aa:aa:aa:aa"),
        _device(ip="192.168.1.20", interface_ip="192.168.1.10"),
        _device(ip="192.168.1.30", mac="02:11:22:33:44:55"),
        _device(ip="192.168.1.40", vendor="Acme Corp."),
    ]

    scanner._add_connections(devices)

    assert [device["connection"] for device in devices] == [
        "Router",
        "Wireless",
        "Wireless",
        "Unknown",
    ]
    assert all(device["connection_detail"] for device in devices)
