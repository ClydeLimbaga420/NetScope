from __future__ import annotations

import math
import threading
import time
from types import SimpleNamespace

import pytest

from core import native
from core.monitoring import MonitoringService, NetworkCounters
from core.native import PingResult
from core.runner import CommandResult, FakeRunner


def _service(snapshot, counters, timestamps, runner=None, clock=None):
    counter_samples = iter(counters)
    clock_samples = iter(timestamps)
    engine = SimpleNamespace(collect_snapshot=lambda: snapshot)
    return MonitoringService(
        engine,
        runner or FakeRunner(),
        None,
        counter_provider=lambda: next(counter_samples),
        clock=clock or (lambda: next(clock_samples)),
    )


def test_status_uses_snapshot_info_and_ping_results(snapshot_factory, monkeypatch):
    import core.info

    snapshot = snapshot_factory()
    monkeypatch.setattr(core.info.socket, "gethostname", lambda: "fixture-host")
    service = _service(
        snapshot,
        [NetworkCounters(1000, 500)],
        [10.0],
    )

    status = service.get_status()

    assert set(status) == {
        "network",
        "traffic",
        "internet_ping",
        "gateway_ping",
        "problems",
    }
    assert status["network"] == {
        "hostname": "fixture-host",
        "local_ip": "192.168.1.10",
        "gateway": "192.168.1.1",
        "interfaces": [
            {
                "name": "Ethernet",
                "ipv4": "192.168.1.10",
                "mac": "aa:bb:cc:dd:ee:01",
                "is_up": True,
                "speed_mbps": 1000,
            }
        ],
        "interface_count": 1,
        "diagnosis": {
            "gateway": "192.168.1.1",
            "issues": [],
            "gateway_in_subnet": True,
            "network_down": False,
        },
    }
    assert status["traffic"] == {
        "download_bytes_sec": 0.0,
        "upload_bytes_sec": 0.0,
        "download_mbps": 0.0,
        "upload_mbps": 0.0,
        "total_received_bytes": 1000,
        "total_sent_bytes": 500,
    }
    assert status["internet_ping"] == {
        "host": "1.1.1.1",
        "latency_ms": 12.0,
        "online": True,
    }
    assert status["gateway_ping"] == {
        "host": "192.168.1.1",
        "latency_ms": 1.0,
        "online": True,
    }
    assert status["problems"] == []


def test_status_counts_each_adapter_once_when_it_has_multiple_ipv4_addresses(
    snapshot_factory,
):
    snapshot = snapshot_factory(
        data={
            "ip_addresses": [
                {
                    "IPAddress": "192.168.1.10",
                    "PrefixLength": 24,
                    "InterfaceAlias": "Ethernet",
                },
                {
                    "IPAddress": "192.168.1.11",
                    "PrefixLength": 24,
                    "InterfaceAlias": "Ethernet",
                },
            ]
        }
    )
    service = _service(
        snapshot,
        [NetworkCounters(0, 0)],
        [10.0],
    )

    network = service.get_status()["network"]

    assert network["interface_count"] == 1
    assert [item["ipv4"] for item in network["interfaces"]] == ["192.168.1.10"]


def test_status_rates_use_receive_and_transmit_counter_deltas(snapshot_factory):
    service = _service(
        snapshot_factory(),
        [
            NetworkCounters(1000, 500),
            NetworkCounters(3400, 1100),
        ],
        [10.0, 12.0],
    )

    service.get_status()
    status = service.get_status()

    assert status["traffic"] == {
        "download_bytes_sec": 1200.0,
        "upload_bytes_sec": 300.0,
        "download_mbps": 0.01,
        "upload_mbps": 0.002,
        "total_received_bytes": 3400,
        "total_sent_bytes": 1100,
    }


@pytest.mark.parametrize("elapsed", [0.0, -1.0])
def test_status_rates_protect_against_nonpositive_elapsed_time(
    snapshot_factory, elapsed
):
    service = _service(
        snapshot_factory(),
        [
            NetworkCounters(100, 100),
            NetworkCounters(200, 300),
        ],
        [10.0, 10.0 + elapsed],
    )

    service.get_status()
    traffic = service.get_status()["traffic"]

    assert math.isfinite(traffic["download_bytes_sec"])
    assert math.isfinite(traffic["upload_bytes_sec"])
    assert traffic["download_bytes_sec"] >= 0
    assert traffic["upload_bytes_sec"] >= 0


def test_status_counter_reset_never_reports_negative_rates(snapshot_factory):
    service = _service(
        snapshot_factory(),
        [
            NetworkCounters(1000, 800),
            NetworkCounters(200, 100),
            NetworkCounters(600, 500),
        ],
        [1.0, 3.0, 5.0],
    )

    service.get_status()
    reset = service.get_status()["traffic"]
    recovered = service.get_status()["traffic"]

    assert reset["download_bytes_sec"] == 0.0
    assert reset["upload_bytes_sec"] == 0.0
    assert recovered["download_bytes_sec"] == 200.0
    assert recovered["upload_bytes_sec"] == 200.0


def test_status_propagates_snapshot_collection_errors():
    def fail_snapshot():
        raise RuntimeError("snapshot unavailable")

    service = MonitoringService(
        SimpleNamespace(collect_snapshot=fail_snapshot),
        FakeRunner(),
        None,
        counter_provider=lambda: NetworkCounters(0, 0),
        clock=lambda: 1.0,
    )

    with pytest.raises(RuntimeError, match="snapshot unavailable"):
        service.get_status()


def test_parse_ping_stats_reads_windows_summary_and_average():
    output = (
        "Packets: Sent = 10, Received = 9, Lost = 1 (10% loss)\n"
        "Minimum = 1ms, Maximum = 5ms, Average = 3ms"
    )

    assert native.parse_ping_stats("1.1.1.1", output, 0) == {
        "host": "1.1.1.1",
        "latency_ms": 3.0,
        "online": True,
        "packet_loss_percent": 10.0,
        "packets_sent": 10,
        "packets_received": 9,
    }


def test_parse_ping_stats_reads_german_summary():
    output = (
        "Pakete: Gesendet = 10, Empfangen = 9, Verloren = 1 (10% Verlust)\n"
        "Minimum = 1ms, Maximum = 5ms, Mittelwert = 3ms"
    )

    assert native.parse_ping_stats("1.1.1.1", output, 0) == {
        "host": "1.1.1.1",
        "latency_ms": 3.0,
        "online": True,
        "packet_loss_percent": 10.0,
        "packets_sent": 10,
        "packets_received": 9,
    }


def test_parse_ping_stats_treats_no_reply_output_as_total_loss():
    result = native.parse_ping_stats(
        "1.1.1.1",
        "Request timed out.\nRequest timed out.",
        1,
        count=2,
    )

    assert result == {
        "host": "1.1.1.1",
        "latency_ms": None,
        "online": False,
        "packet_loss_percent": 100.0,
        "packets_sent": 2,
        "packets_received": 0,
    }


def test_parse_ping_stats_rejects_malformed_summary():
    with pytest.raises(ValueError, match="could not parse"):
        native.parse_ping_stats("1.1.1.1", "ping output without packet statistics", 0)


def test_packet_loss_samples_both_targets_through_runner(snapshot_factory):
    class ConcurrentRunner:
        def __init__(self):
            self.barrier = __import__("threading").Barrier(2)
            self.calls = []

        def run(self, args, *, timeout=None, **_kwargs):
            self.calls.append((tuple(args), timeout))
            self.barrier.wait(timeout=2)
            output = (
                "Packets: Sent = 10, Received = 10, Lost = 0 (0% loss)\n"
                "Minimum = 1ms, Maximum = 2ms, Average = 1ms"
            )
            return CommandResult(tuple(args), 0, stdout=output)

    runner = ConcurrentRunner()
    service = _service(
        snapshot_factory(),
        [NetworkCounters(0, 0)],
        [10.0],
        runner=runner,
    )

    result = service._collect_packet_loss(service.engine.collect_snapshot())

    assert result == {
        "count": 10,
        "internet": {
            "host": "1.1.1.1",
            "latency_ms": 1.0,
            "online": True,
            "packet_loss_percent": 0.0,
            "packets_sent": 10,
            "packets_received": 10,
        },
        "gateway": {
            "host": "192.168.1.1",
            "latency_ms": 1.0,
            "online": True,
            "packet_loss_percent": 0.0,
            "packets_sent": 10,
            "packets_received": 10,
        },
    }
    assert len(runner.calls) == 2
    assert {call[0][-1] for call in runner.calls} == {"1.1.1.1", "192.168.1.1"}
    assert all(call[1] == 15.0 for call in runner.calls)
    assert all("10" in call[0] for call in runner.calls)


def test_packet_loss_runner_timeout_is_an_error(snapshot_factory):
    class TimeoutRunner:
        def run(self, args, *, timeout=None, **_kwargs):
            return CommandResult(
                tuple(args),
                124,
                timed_out=True,
                error="command timed out",
            )

    service = _service(
        snapshot_factory(),
        [NetworkCounters(0, 0)],
        [10.0],
        runner=TimeoutRunner(),
    )

    with pytest.raises(RuntimeError, match="timed out"):
        service._collect_packet_loss(service.engine.collect_snapshot())


def _wait_for_result(request, state):
    deadline = time.monotonic() + 2.0
    result = request()
    while result.state == "pending" and time.monotonic() < deadline:
        time.sleep(0.01)
        result = request()
    assert result.state == state
    return result


def test_background_tasks_are_independent_deduplicated_and_nonblocking(
    snapshot_factory,
):
    devices_started = threading.Event()
    release_devices = threading.Event()
    packet_calls = []
    packet_lock = threading.Lock()
    packet_started = threading.Event()
    release_packet = threading.Event()

    class BlockingRunner:
        def run(self, args, *, timeout=None, **_kwargs):
            with packet_lock:
                packet_calls.append(tuple(args))
                if len(packet_calls) == 2:
                    packet_started.set()
            assert release_packet.wait(2)
            output = (
                "Packets: Sent = 10, Received = 10, Lost = 0 (0% loss)\n"
                "Minimum = 1ms, Maximum = 2ms, Average = 1ms"
            )
            return CommandResult(tuple(args), 0, stdout=output)

    service = _service(
        snapshot_factory(),
        [NetworkCounters(100, 50)],
        [10.0],
        runner=BlockingRunner(),
        clock=lambda: 10.0,
    )
    discovery_calls = []

    def blocked_discovery(snapshot, *, force=False):
        discovery_calls.append((snapshot, force))
        devices_started.set()
        assert release_devices.wait(2)
        return [{"ip": "192.168.1.20"}]

    service.device_discovery.discover = blocked_discovery

    assert service.request_devices().state == "pending"
    assert devices_started.wait(1)
    assert service.request_packet_loss().state == "pending"
    assert packet_started.wait(1)
    assert service.request_devices().state == "pending"
    assert service.request_packet_loss().state == "pending"
    assert len(discovery_calls) == 1
    assert len(packet_calls) == 2

    started = time.monotonic()
    status = service.get_status()
    assert time.monotonic() - started < 0.5
    assert status["network"]["gateway"] == "192.168.1.1"

    release_devices.set()
    release_packet.set()
    devices = _wait_for_result(service.request_devices, "ready")
    packet_loss = _wait_for_result(service.request_packet_loss, "ready")

    assert devices.value == [{"ip": "192.168.1.20"}]
    assert packet_loss.value["count"] == 10
    assert discovery_calls[0][1] is True


def test_status_reuses_collected_snapshot(snapshot_factory):
    snapshot = snapshot_factory()
    collect_calls = []

    def collect():
        collect_calls.append(1)
        return snapshot

    engine = SimpleNamespace(collect_snapshot=collect)
    service = MonitoringService(
        engine,
        FakeRunner(),
        None,
        counter_provider=lambda: NetworkCounters(0, 0),
        clock=lambda: 10.0,
    )

    service.get_status()
    service.get_status()

    assert len(collect_calls) == 1


def test_device_discovery_reuses_cached_snapshot(snapshot_factory):
    snapshot = snapshot_factory()
    collect_calls = []
    engine = SimpleNamespace(
        collect_snapshot=lambda: collect_calls.append(1) or snapshot
    )
    service = MonitoringService(
        engine,
        FakeRunner(),
        None,
        counter_provider=lambda: NetworkCounters(0, 0),
        clock=lambda: 10.0,
    )
    service.get_snapshot()
    service.device_discovery.discover = lambda _snap, **_kwargs: []

    result = _wait_for_result(service.request_devices, "ready")

    assert result.value == []
    assert collect_calls == [1]


def test_background_discovery_failure_is_returned_as_error(snapshot_factory):
    service = _service(
        snapshot_factory(),
        [NetworkCounters(0, 0)],
        [10.0],
        clock=lambda: 10.0,
    )

    def fail_discovery(_snapshot, *, force=False):
        raise RuntimeError("device scan failed")

    service.device_discovery.discover = fail_discovery

    result = _wait_for_result(service.request_devices, "error")

    assert result.value is None
    assert result.error == "device scan failed"
    assert service.request_devices().error == "device scan failed"
