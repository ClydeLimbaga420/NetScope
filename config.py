"""Shared application and diagnostic configuration constants."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "NetScope"
APP_VERSION = "0.4.0"

PING_TIMEOUT_SECONDS = 1

# --- command execution ---------------------------------------------------

DEFAULT_COMMAND_TIMEOUT_SECONDS = 20.0
PING_COMMAND_TIMEOUT_SECONDS = 5.0
POWERSHELL_TIMEOUT_SECONDS = 30.0
POWERSHELL_EXE = "powershell.exe"

# --- resource limits (low-end device safety) -----------------------------
#
# A local scan or a burst of UI requests used to be able to spawn dozens of
# child processes at once, which stalls or crashes low-memory machines. Every
# cap below is deliberately conservative but can be raised with an environment
# variable, e.g. NETSCOPE_MAX_CONCURRENT_COMMANDS=16.

def _int_env(name: str, default: int, *, minimum: int = 1, maximum: int = 4096) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


# Global ceiling on simultaneously running child processes (all sources).
MAX_CONCURRENT_COMMANDS = _int_env("NETSCOPE_MAX_CONCURRENT_COMMANDS", 8, maximum=64)

# Device discovery: scan a bounded portion of the local subnet with a small
# worker pool. 256 hosts covers a typical home /24; larger prefixes are capped.
DEVICE_SCAN_MAX_HOSTS = _int_env("NETSCOPE_SCAN_MAX_HOSTS", 256, maximum=4096)
DEVICE_SCAN_MAX_WORKERS = _int_env("NETSCOPE_SCAN_MAX_WORKERS", 8, maximum=64)
DEVICE_NAME_MAX_WORKERS = _int_env("NETSCOPE_NAME_MAX_WORKERS", 4, maximum=32)
DEVICE_SCAN_CACHE_SECONDS = _int_env("NETSCOPE_SCAN_CACHE_SECONDS", 60, maximum=3600)
DEVICE_NAME_CACHE_SECONDS = _int_env("NETSCOPE_NAME_CACHE_SECONDS", 600, maximum=86400)

# Monitoring refresh intervals. Longer windows mean fewer snapshots and far
# fewer spawned processes while the dashboard stays open.
MONITORING_SNAPSHOT_CACHE_SECONDS = _int_env(
    "NETSCOPE_SNAPSHOT_CACHE_SECONDS", 30, maximum=3600
)
MONITORING_DEVICE_CACHE_SECONDS = _int_env(
    "NETSCOPE_DEVICE_CACHE_SECONDS", 60, maximum=3600
)
MONITORING_PACKET_LOSS_CACHE_SECONDS = _int_env(
    "NETSCOPE_PACKET_LOSS_CACHE_SECONDS", 60, maximum=3600
)

# A quick, positive-only internet ping is used while the full snapshot is still
# collecting. It is cached briefly so a stable connection can show Connected in
# about one second without spawning a ping on every UI poll.
MONITORING_QUICK_PING_CACHE_SECONDS = _int_env(
    "NETSCOPE_QUICK_PING_CACHE_SECONDS", 10, maximum=300
)

# Each unreachable remote-LAN next hop can cost a full ping timeout before the
# dashboard snapshot completes, so keep this small on low-end machines.
SNAPSHOT_MAX_REMOTE_PINGS = _int_env("NETSCOPE_MAX_REMOTE_PINGS", 2, maximum=32)

# Log hygiene. Command-heavy scans (device discovery in particular) can write
# thousands of JSON lines in a few minutes. On a low-end machine the growing
# file and the whole-file reads behind the log view can stall the app, so the
# live front ends clear the rotating log on this interval. Override with
# NETSCOPE_LOG_CLEAR_INTERVAL_SECONDS; 0 disables the automatic clear.
LOG_CLEAR_INTERVAL_SECONDS = _int_env(
    "NETSCOPE_LOG_CLEAR_INTERVAL_SECONDS", 180, minimum=0, maximum=86400
)

LOG_MAX_BYTES_MB = _int_env("NETSCOPE_LOG_MAX_MB", 2, minimum=1, maximum=64)
LOG_BACKUP_COUNT = _int_env("NETSCOPE_LOG_BACKUP_COUNT", 3, maximum=20)

MIN_FREE_DISK_MB = _int_env("NETSCOPE_MIN_FREE_DISK_MB", 250, minimum=10, maximum=10000)
MIN_FREE_DISK_BYTES = MIN_FREE_DISK_MB * 1024 * 1024

REPORT_MAX_FILES = _int_env("NETSCOPE_REPORT_MAX_FILES", 24, maximum=1000)
REPORT_MAX_BYTES = _int_env("NETSCOPE_REPORT_MAX_MB", 32, maximum=10000) * 1024 * 1024
BACKUP_MAX_FILES = _int_env("NETSCOPE_BACKUP_MAX_FILES", 60, maximum=1000)
BACKUP_MAX_BYTES = _int_env("NETSCOPE_BACKUP_MAX_MB", 64, maximum=10000) * 1024 * 1024
ARTIFACT_MAX_AGE_SECONDS = (
    _int_env("NETSCOPE_ARTIFACT_MAX_AGE_DAYS", 180, maximum=3650) * 86400
)

WEBVIEW_STORAGE_ENABLED = os.environ.get("NETSCOPE_WEBVIEW_STORAGE", "1") != "0"

# The server used to exit silently after 120s without a browser heartbeat.
# WebView2 throttles renderer timers on a busy or backgrounded low-end machine,
# so a live window can miss several pings and get killed mid-scan. The native
# window host now keeps the server alive explicitly; this longer window is a
# second line of defence for browser-fallback launches.
WEB_IDLE_SHUTDOWN_SECONDS = _int_env(
    "NETSCOPE_WEB_IDLE_SHUTDOWN_SECONDS", 300, minimum=30, maximum=86400
)

# Full process termination. A graceful stop is given this long to let the
# server exit before remaining NetScope processes are killed.
PROCESS_EXIT_WAIT_SECONDS = 8.0
PROCESS_TERMINATION_GRACE_SECONDS = 2.0

# --- diagnostic pipeline -------------------------------------------------

# Local device first, outward. Keep this order stable: the engine reports the
# first failing layer in this sequence.
PIPELINE_LAYERS = (
    "adapter",
    "services",
    "ip",
    "gateway",
    "lan",
    "dns",
    "internet",
    "stack",
)

# Hosts used by the internet checks. Public, well known, ping friendly.
INTERNET_PING_HOSTS = ("1.1.1.1", "8.8.8.8")
CAPTIVE_PORTAL_URL = "http://www.msftconnecttest.com/connecttest.txt"
CAPTIVE_PORTAL_EXPECTED = "Microsoft Connect Test"

# --- filesystem ----------------------------------------------------------

def local_app_data() -> Path:
    """Return the per-user LOCALAPPDATA directory, with a fallback."""

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base)
        return Path.home() / "AppData" / "Local"

    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def data_dir() -> Path:
    """Return NetScope's data directory.

    ``NETSCOPE_DATA_DIR`` overrides the whole path. Elevation passes the
    original session's directory so an elevated process started under a
    different Windows account still writes its lock/boot token where the
    original UI is watching.
    """

    override = os.environ.get("NETSCOPE_DATA_DIR")
    if override:
        return Path(override)
    return local_app_data() / APP_NAME


def log_dir() -> Path:
    return data_dir() / "logs"


def report_dir() -> Path:
    return data_dir() / "reports"


def backup_dir() -> Path:
    return data_dir() / "backups"


def snapshot_cache_path() -> Path:
    return data_dir() / "snapshot.json"
