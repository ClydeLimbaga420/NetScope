import socket

import psutil
from flask import Flask, jsonify, render_template

from config import APP_NAME, HOST, PORT
from modules.network_info import get_network_info
from modules.bandwidth import BandwidthMonitor
from modules.ping_monitor import ping_host
from modules.device_scanner import get_arp_devices
from modules.diagnostics import list_diagnostics, run_diagnostic


def _status_problems(network, internet_ping, gateway_ping):
    problems = []
    diagnosis = network.get("diagnosis") or {}
    config_issues = diagnosis.get("issues") or []
    network_down_issue = next(
        (issue for issue in config_issues if issue.get("id") == "network-down"),
        None,
    )

    for issue in config_issues:
        problems.append({
            "source": "configuration",
            "severity": issue.get("severity", "warning"),
            "message": issue.get("message"),
        })

    gateway = network.get("gateway")
    if gateway and not gateway_ping.get("online"):
        in_subnet = diagnosis.get("gateway_in_subnet")
        if in_subnet is False:
            message = (
                f"Default gateway {gateway} did not respond and appears to be "
                "outside this computer's subnet. The gateway may be configured "
                "incorrectly."
            )
        else:
            message = (
                f"Default gateway {gateway} did not respond. The router may be "
                "offline, unreachable, or blocking ping requests."
            )
        problems.append({
            "source": "gateway",
            "severity": "error",
            "message": message,
        })

    if not internet_ping.get("online"):
        if network_down_issue and network_down_issue.get("message"):
            message = network_down_issue["message"]
        elif gateway and gateway_ping.get("online"):
            message = (
                "The default gateway is reachable, but the internet is not. "
                "The problem may be with the router's internet connection, "
                "your ISP, or upstream routing."
            )
        elif gateway:
            message = (
                "Network connection problem: the internet is unreachable. "
                "Check the default gateway and local network connection first."
            )
        else:
            message = (
                "Network is down or disconnected: the internet is unreachable "
                "and no default gateway was detected."
            )
        problems.append({
            "source": "internet",
            "severity": "error",
            "message": message,
        })

    deduped = []
    seen = set()
    for problem in problems:
        key = problem.get("message")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(problem)

    return deduped

app = Flask(__name__)

bandwidth_monitor = BandwidthMonitor()


def _lan_urls():
    urls = set()

    try:
        interfaces = psutil.net_if_addrs()
    except (OSError, AttributeError):
        return []

    for addresses in interfaces.values():
        for address in addresses:
            if address.family != socket.AF_INET:
                continue

            ip = address.address

            if (
                not ip
                or ip.startswith("127.")
                or ip.startswith("169.254.")
            ):
                continue

            urls.add(f"http://{ip}:{PORT}")

    return sorted(urls)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    network = get_network_info()
    traffic = bandwidth_monitor.get_rates()

    gateway = network.get("gateway")

    internet_ping = ping_host("1.1.1.1")

    gateway_ping = (
        ping_host(gateway)
        if gateway
        else {
            "host": None,
            "latency_ms": None,
            "online": False,
            "reason": "No default gateway was detected.",
        }
    )

    problems = _status_problems(network, internet_ping, gateway_ping)

    return jsonify({
        "network": network,
        "traffic": traffic,
        "internet_ping": internet_ping,
        "gateway_ping": gateway_ping,
        "problems": problems,
    })


@app.route("/api/devices")
def api_devices():
    return jsonify({
        "devices": get_arp_devices()
    })


@app.route("/api/diagnostics")
def api_diagnostics():
    return jsonify(list_diagnostics())


@app.route("/api/diagnostics/<step_id>/run", methods=["POST"])
def api_run_diagnostic(step_id):
    try:
        return jsonify(run_diagnostic(step_id))

    except KeyError:
        return jsonify({
            "error": "Unknown diagnostic step"
        }), 404


if __name__ == "__main__":
    urls = _lan_urls()

    print(f"{APP_NAME} is reachable on this computer:")
    print(f"  http://127.0.0.1:{PORT}")

    if urls:
        print("On the local network:")
        for url in urls:
            print(f"  {url}")

    print()

    app.run(
        host=HOST,
        port=PORT,
        debug=False,
        threaded=True
    )