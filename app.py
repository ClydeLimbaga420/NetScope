from flask import Flask, jsonify, render_template

from modules.network_info import get_network_info
from modules.bandwidth import BandwidthMonitor
from modules.ping_monitor import ping_host
from modules.device_scanner import get_arp_devices

app = Flask(__name__)

bandwidth_monitor = BandwidthMonitor()


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
        else {"host": None, "latency_ms": None, "online": False}
    )

    return jsonify({
        "network": network,
        "traffic": traffic,
        "internet_ping": internet_ping,
        "gateway_ping": gateway_ping
    })


@app.route("/api/devices")
def api_devices():
    return jsonify({
        "devices": get_arp_devices()
    })


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True
    )