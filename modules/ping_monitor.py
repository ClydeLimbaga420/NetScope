import platform
import re
import subprocess

from config import PING_TIMEOUT_SECONDS


def ping_host(host):

    if not host:

        return {
            "host": None,
            "latency_ms": None,
            "online": False
        }

    system = platform.system().lower()

    if system == "windows":

        command = [
            "ping",
            "-n", "1",
            "-w", str(PING_TIMEOUT_SECONDS * 1000),
            host
        ]

    else:

        command = [
            "ping",
            "-c", "1",
            "-W", str(PING_TIMEOUT_SECONDS),
            host
        ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PING_TIMEOUT_SECONDS + 2,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0
            )
        )

        output = result.stdout + result.stderr

        match = re.search(
            r"time[=<]([0-9.]+)\s*ms",
            output,
            re.I
        )

        if result.returncode == 0:

            return {
                "host": host,
                "latency_ms": (
                    float(match.group(1))
                    if match
                    else None
                ),
                "online": True
            }

    except (OSError, subprocess.SubprocessError):
        pass

    return {
        "host": host,
        "latency_ms": None,
        "online": False
    }