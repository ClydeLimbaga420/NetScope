"""NetScope configuration constants.

Kept deliberately small and dependency free. The Flask dashboard imports
``PING_TIMEOUT_SECONDS`` from here, so keep that name stable.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "NetScope"
APP_VERSION = "0.3.0"

HOST = "0.0.0.0"

PORT = 5000

REFRESH_INTERVAL_MS = 2000

PING_TIMEOUT_SECONDS = 1

# --- command execution ---------------------------------------------------

DEFAULT_COMMAND_TIMEOUT_SECONDS = 20.0
PING_COMMAND_TIMEOUT_SECONDS = 5.0
POWERSHELL_TIMEOUT_SECONDS = 30.0
POWERSHELL_EXE = "powershell.exe"

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
    """Return the per-user data directory, with a cross-platform fallback."""

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base)
        return Path.home() / "AppData" / "Local"

    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def data_dir() -> Path:
    return local_app_data() / APP_NAME


def log_dir() -> Path:
    return data_dir() / "logs"


def report_dir() -> Path:
    return data_dir() / "reports"


def backup_dir() -> Path:
    return data_dir() / "backups"
