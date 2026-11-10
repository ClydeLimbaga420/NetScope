import platform
import re
import subprocess

from config import PING_TIMEOUT_SECONDS


def ping_host(host, count=1):

    if not host:

        result = {
            "host": None,
            "latency_ms": None,
            "online": False
        }

        if count and count > 1:
            result.update({
                "packet_loss_percent": None,
                "packets_sent": 0,
                "packets_received": 0,
            })

        return result

    system = platform.system().lower()

    if system == "windows":

        command = [
            "ping",
            "-n", str(count),
            "-w", str(PING_TIMEOUT_SECONDS * 1000),
            host
        ]

    else:

        command = [
            "ping",
            "-c", str(count),
            "-W", str(PING_TIMEOUT_SECONDS),
            host
        ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=(PING_TIMEOUT_SECONDS * max(count, 1)) + 5,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0
            )
        )

        output = (result.stdout or "") + "\n" + (result.stderr or "")

        latency_ms = _parse_latency(output, count=count)
        sent, received, loss = _parse_packet_loss(output, count=count)
        online = received > 0 if received is not None else result.returncode == 0

        payload = {
            "host": host,
            "latency_ms": latency_ms,
            "online": online,
        }

        if count and count > 1:
            payload.update({
                "packet_loss_percent": loss,
                "packets_sent": sent,
                "packets_received": received,
            })

        return payload

    except (OSError, subprocess.SubprocessError):
        pass

    payload = {
        "host": host,
        "latency_ms": None,
        "online": False,
    }

    if count and count > 1:
        payload.update({
            "packet_loss_percent": 100.0,
            "packets_sent": count,
            "packets_received": 0,
        })

    return payload


def _parse_latency(output, count=1):
    if count and count > 1:
        avg = re.search(
            r"(?:Average|rtt [^=]*=\s*[0-9.]+/[0-9.]+/)[ =]*([0-9.]+)",
            output,
            re.I,
        )
        if avg:
            try:
                return float(avg.group(1))
            except ValueError:
                pass

    match = re.search(
        r"time[=<]([0-9.]+)\s*ms",
        output,
        re.I
    )

    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None

    return None


def _parse_packet_loss(output, count=1):
    # Windows: "Packets: Sent = 4, Received = 4, Lost = 0 (0% loss)"
    # Linux/macOS: "4 packets transmitted, 4 received, 0% packet loss, time 3004ms"
    m = re.search(
        r"Sent\s*=\s*(\d+).*?Received\s*=\s*(\d+).*?(?:Lost\s*=\s*\d+\s*\()?\s*(\d+(?:\.\d+)?)%\s*loss",
        output,
        re.I | re.S,
    )
    if m:
        sent = int(m.group(1))
        received = int(m.group(2))
        loss = float(m.group(3))
        return sent, received, loss

    m = re.search(
        r"(\d+)\s+packets?\s+transmitted,\s*(\d+)\s+(?:packets?\s+)?received.*?(\d+(?:\.\d+)?)%\s*(?:packet\s*)?loss",
        output,
        re.I | re.S,
    )
    if m:
        sent = int(m.group(1))
        received = int(m.group(2))
        loss = float(m.group(3))
        return sent, received, loss

    if count and count > 1:
        times = re.findall(r"time[=<]([0-9.]+)\s*ms", output, re.I)
        received = len(times)
        sent = int(count)
        if received > 0:
            loss = max(0.0, (1 - (received / sent)) * 100.0)
            return sent, received, round(loss, 1)

    return None, None, None


def ping_host_stats(host, count=10):
    return ping_host(host, count=count)