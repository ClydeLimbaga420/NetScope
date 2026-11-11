"""Static descriptions of the checks the engine can run.

The web UI shows this list before a diagnosis so users can see what will be
checked. Actual results replace these planned rows as they stream in. Keep the
ids/titles aligned with the titles produced by the check modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.models import Layer


@dataclass(frozen=True)
class CheckDescriptor:
    id: str
    layer: Layer
    title: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "layer": self.layer.value, "title": self.title}


CHECK_DESCRIPTORS: tuple[CheckDescriptor, ...] = (
    CheckDescriptor("ADP-01", Layer.ADAPTER, "Adapter enabled"),
    CheckDescriptor("ADP-03", Layer.ADAPTER, "Adapter power saving"),
    CheckDescriptor("ADP-04", Layer.ADAPTER, "Driver health"),
    CheckDescriptor("ADP-05", Layer.ADAPTER, "Link speed"),
    CheckDescriptor("ADP-06", Layer.ADAPTER, "Interface priority"),
    CheckDescriptor("SVC-01", Layer.SERVICES, "WLAN AutoConfig"),
    CheckDescriptor("SVC-02", Layer.SERVICES, "DHCP Client"),
    CheckDescriptor("SVC-03", Layer.SERVICES, "DNS Client"),
    CheckDescriptor("SVC-04", Layer.SERVICES, "Network Location Awareness"),
    CheckDescriptor("SVC-05", Layer.SERVICES, "Base Filtering Engine"),
    CheckDescriptor("SVC-06", Layer.SERVICES, "File and printer sharing stack"),
    CheckDescriptor("IP-01", Layer.IP, "DHCP lease / APIPA"),
    CheckDescriptor("IP-02", Layer.IP, "DHCP lease matches the network"),
    CheckDescriptor("IP-03", Layer.IP, "Duplicate address"),
    CheckDescriptor("IP-04", Layer.IP, "Static address matches the network"),
    CheckDescriptor("IP-05", Layer.IP, "Default route"),
    CheckDescriptor("IP-06", Layer.IP, "Overlapping routes"),
    CheckDescriptor("IP-07", Layer.IP, "Virtual network overlap"),
    CheckDescriptor("GW-01", Layer.GATEWAY, "Gateway reachability"),
    CheckDescriptor("LAN-04", Layer.LAN, "Network profile"),
    CheckDescriptor("LAN-05", Layer.LAN, "Discovery / sharing firewall rules"),
    CheckDescriptor("LAN-08", Layer.LAN, "SMB2/3 client"),
    CheckDescriptor("DNS-01", Layer.DNS, "Windows resolver"),
    CheckDescriptor("DNS-02", Layer.DNS, "DNS resolution"),
    CheckDescriptor("DNS-03", Layer.DNS, "Hosts file overrides"),
    CheckDescriptor("NET-PING", Layer.INTERNET, "Internet reachability"),
    CheckDescriptor("NET-01", Layer.INTERNET, "Captive portal"),
    CheckDescriptor("NET-03", Layer.INTERNET, "WinHTTP system proxy"),
    CheckDescriptor("NET-04", Layer.INTERNET, "User (WinINET) proxy"),
    CheckDescriptor("NET-06", Layer.INTERNET, "System clock"),
    CheckDescriptor("STK-01", Layer.STACK, "Winsock catalog"),
    CheckDescriptor("NET-10", Layer.STACK, "TCP receive window auto-tuning"),
)
