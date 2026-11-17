"""Load the bundled offline OUI vendor map."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Mapping


_OUI_PREFIX = re.compile(r"[0-9A-Fa-f]{6}\Z")
_MAC_ADDRESS = re.compile(r"[0-9A-Fa-f]{12}\Z")


def load_oui_vendors() -> dict[str, str]:
    try:
        resource = files("core").joinpath("oui_vendors.json")
        with resource.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not load OUI vendor resource core/oui_vendors.json: {exc}"
        ) from exc

    if not isinstance(data, dict) or not data:
        raise RuntimeError(
            "OUI vendor resource core/oui_vendors.json is empty or invalid"
        )

    vendors: dict[str, str] = {}
    for prefix, vendor in data.items():
        if not isinstance(prefix, str) or not _OUI_PREFIX.fullmatch(prefix):
            raise RuntimeError(
                f"OUI vendor resource contains an invalid prefix: {prefix!r}"
            )
        if not isinstance(vendor, str) or not vendor.strip():
            raise RuntimeError(
                f"OUI vendor resource contains an invalid vendor for {prefix}"
            )
        vendors[prefix.upper()] = vendor
    return vendors


def lookup_vendor(
    mac: str | None,
    mapping: Mapping[str, str] | None = None,
) -> str | None:
    compact = re.sub(r"[:-]", "", str(mac or ""))
    if not _MAC_ADDRESS.fullmatch(compact):
        return None
    vendors = mapping if mapping is not None else load_oui_vendors()
    return vendors.get(compact[:6].upper())
