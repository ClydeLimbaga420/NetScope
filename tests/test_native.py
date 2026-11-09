from __future__ import annotations

from pathlib import Path

from core.native import (
    parse_arp,
    parse_default_gateway,
    parse_default_routes,
    parse_netsh_winhttp_proxy,
    parse_ping,
    parse_tcp_autotuning,
    parse_winsock_catalog,
    ping_args,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_ping_english():
    result = parse_ping("1.1.1.1", _text("sample_ping_en.txt"), 0)
    assert result.online
    assert result.latency_ms == 12.0


def test_parse_ping_german():
    result = parse_ping("1.1.1.1", _text("sample_ping_de.txt"), 0)
    assert result.online
    assert result.latency_ms == 12.0


def test_parse_ping_malformed_and_failure():
    result = parse_ping("1.1.1.1", "garbage", 1)
    assert not result.online
    assert result.latency_ms is None

    result = parse_ping("1.1.1.1", "Reply from 10.0.0.1: Destination host unreachable.", 0)
    assert not result.online


def test_parse_default_gateway():
    assert parse_default_gateway(_text("sample_ipconfig.txt")) == "192.168.1.1"
    assert parse_default_gateway("no gateway here") is None
    assert parse_default_gateway("Default Gateway . . . . . : 0.0.0.0") is None


def test_parse_arp_filters_noise():
    entries = parse_arp(_text("sample_arp.txt"))
    addresses = {entry["ip"] for entry in entries}
    assert "192.168.1.1" in addresses
    assert "192.168.1.20" in addresses
    assert "224.0.0.22" not in addresses
    assert "255.255.255.255" not in addresses
    mac = next(entry["mac"] for entry in entries if entry["ip"] == "192.168.1.1")
    assert mac == "aa:bb:cc:dd:ee:ff"


def test_parse_default_routes():
    routes = parse_default_routes(_text("sample_route_print.txt"))
    assert routes[0]["gateway"] == "192.168.1.1"
    assert routes[0]["metric"] == 25


def test_parse_tcp_autotuning():
    assert parse_tcp_autotuning(_text("sample_netsh_tcp.txt")) == "normal"
    assert parse_tcp_autotuning("nothing") is None


def test_parse_winhttp_proxy():
    assert parse_netsh_winhttp_proxy(_text("sample_netsh_winhttp.txt")) == "proxy.corp.example:8080"
    assert parse_netsh_winhttp_proxy("Direct access (no proxy server).") is None


def test_parse_winsock_catalog():
    vendors = parse_winsock_catalog(_text("sample_winsock.txt"))
    assert vendors == ["NetLimiter LSP"]


def test_ping_args_use_os_flags():
    args = ping_args("1.1.1.1", 1)
    assert args[0] == "ping"
    assert args[-1] == "1.1.1.1"
    if __import__("os").name == "nt":
        assert "-n" in args
        assert "-w" in args
    else:
        assert "-c" in args
