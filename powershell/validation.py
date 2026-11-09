"""Strict validators for every value that may reach a command.

Values are also passed to PowerShell as separate process arguments, never
interpolated into script text. Validation is defence in depth.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

MAX_NAME_LENGTH = 128
MAX_HOST_LENGTH = 253
MAX_PATH_LENGTH = 4096

# Letters, digits, spaces and a small set of punctuation seen in adapter and
# Wi-Fi profile names. Deliberately excludes quotes, backticks, semicolons,
# pipes, ampersands, redirection, dollar signs and control characters.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-()#+/]{0,127}$")
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}"
    r"(?:\.[A-Za-z0-9-]{1,63})*\.?$"
)
_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-()#+/]{0,127}$")


class ValidationError(ValueError):
    """Raised when user input is not safe to pass to a command."""


def _reject_unsafe(value: str) -> None:
    if not isinstance(value, str):
        raise ValidationError("value must be a string")
    if not value or len(value) > MAX_PATH_LENGTH:
        raise ValidationError("value is empty or too long")
    if any(ord(char) < 0x20 for char in value):
        raise ValidationError("value contains control characters")
    if "\x00" in value:
        raise ValidationError("value contains NUL")


def validate_host(value: str) -> str:
    """Accept an IPv4/IPv6 literal or a strict DNS hostname."""

    _reject_unsafe(value)
    value = value.strip()
    if not value or len(value) > MAX_HOST_LENGTH:
        raise ValidationError(f"invalid host: {value!r}")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not _HOSTNAME.match(value):
        raise ValidationError(f"invalid host: {value!r}")
    return value


def validate_ip(value: str) -> str:
    _reject_unsafe(value)
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise ValidationError(f"invalid IP address: {value!r}") from exc


def validate_port(value: int | str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid port: {value!r}") from exc
    if not 1 <= port <= 65535:
        raise ValidationError(f"port out of range: {port}")
    return port


def validate_port_spec(value: str) -> str:
    """Accept ``80``, ``80,443`` or ``1-1024`` port specifications."""

    _reject_unsafe(value)
    spec = value.strip()
    if not spec or len(spec) > 512:
        raise ValidationError("invalid port specification")
    for part in spec.split(","):
        part = part.strip()
        if not part:
            raise ValidationError("invalid port specification")
        if "-" in part:
            start, _, end = part.partition("-")
            first, last = validate_port(start), validate_port(end)
            if first > last:
                raise ValidationError(f"invalid port range: {part}")
        else:
            validate_port(part)
    return spec


def validate_adapter_name(value: str) -> str:
    _reject_unsafe(value)
    value = value.strip()
    if not _SAFE_NAME.match(value):
        raise ValidationError(f"invalid adapter name: {value!r}")
    return value


def validate_profile_name(value: str) -> str:
    _reject_unsafe(value)
    value = value.strip()
    if not _PROFILE.match(value):
        raise ValidationError(f"invalid profile name: {value!r}")
    return value


def validate_fix_id(value: str) -> str:
    _reject_unsafe(value)
    if not re.fullmatch(r"[A-Z]{2,5}-[0-9]{2}", value.strip()):
        raise ValidationError(f"invalid fix id: {value!r}")
    return value.strip()


def validate_path(value: str) -> str:
    _reject_unsafe(value)
    path = Path(value)
    return str(path)


def validate_choice(value: str, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise ValidationError(f"invalid choice: {value!r}")
    return value


def validate_param_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""):
        raise ValidationError(f"invalid PowerShell parameter name: {value!r}")
    return value
