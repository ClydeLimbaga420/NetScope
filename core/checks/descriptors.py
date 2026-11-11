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
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer.value,
            "title": self.title,
            "description": self.description,
        }


CHECK_DESCRIPTORS: tuple[CheckDescriptor, ...] = (
    CheckDescriptor("ADP-01", Layer.ADAPTER, "Adapter enabled", "Checks that your network adapter (Wi-Fi or Ethernet) is turned on."),
    CheckDescriptor("ADP-03", Layer.ADAPTER, "Adapter power saving", "Checks if Windows may power down the adapter to save battery."),
    CheckDescriptor("ADP-04", Layer.ADAPTER, "Driver health", "Checks the adapter driver for reported problems."),
    CheckDescriptor("ADP-05", Layer.ADAPTER, "Link speed", "Checks the connection speed between this PC and the router."),
    CheckDescriptor("ADP-06", Layer.ADAPTER, "Interface priority", "Checks the order Windows prefers network adapters."),
    CheckDescriptor("SVC-01", Layer.SERVICES, "WLAN AutoConfig", "Checks the service that manages Wi-Fi connections."),
    CheckDescriptor("SVC-02", Layer.SERVICES, "DHCP Client", "Checks the service that gets this PC an IP address automatically."),
    CheckDescriptor("SVC-03", Layer.SERVICES, "DNS Client", "Checks the service that turns website names into addresses."),
    CheckDescriptor("SVC-04", Layer.SERVICES, "Network Location Awareness", "Checks the service that identifies the network type."),
    CheckDescriptor("SVC-05", Layer.SERVICES, "Base Filtering Engine", "Checks a core service the firewall depends on."),
    CheckDescriptor("SVC-06", Layer.SERVICES, "File and printer sharing stack", "Checks the services used for sharing files and printers."),
    CheckDescriptor("IP-01", Layer.IP, "DHCP lease / APIPA", "Checks whether this PC received a real address or made one up."),
    CheckDescriptor("IP-02", Layer.IP, "DHCP lease matches the network", "Checks that this PC's address belongs to the router's network."),
    CheckDescriptor("IP-03", Layer.IP, "Duplicate address", "Checks whether another device is using the same address."),
    CheckDescriptor("IP-04", Layer.IP, "Static address matches the network", "Checks that a manually set address fits the network."),
    CheckDescriptor("IP-05", Layer.IP, "Default route", "Checks that this PC knows how to send traffic to the internet."),
    CheckDescriptor("IP-06", Layer.IP, "Overlapping routes", "Checks for duplicate route entries that confuse traffic."),
    CheckDescriptor("IP-07", Layer.IP, "Virtual network overlap", "Checks if virtual adapters clash with the real network."),
    CheckDescriptor("GW-01", Layer.GATEWAY, "Gateway reachability", "Checks that the router answers when pinged."),
    CheckDescriptor("LAN-04", Layer.LAN, "Network profile", "Checks whether the network is set to Public or Private."),
    CheckDescriptor("LAN-05", Layer.LAN, "Discovery / sharing firewall rules", "Checks firewall rules that allow seeing other devices."),
    CheckDescriptor("LAN-08", Layer.LAN, "SMB2/3 client", "Checks the Windows file-sharing protocol version."),
    CheckDescriptor("DNS-01", Layer.DNS, "Windows resolver", "Checks the DNS resolver cache for problems."),
    CheckDescriptor("DNS-02", Layer.DNS, "DNS resolution", "Checks that website names resolve to addresses."),
    CheckDescriptor("DNS-03", Layer.DNS, "Hosts file overrides", "Checks for custom entries that redirect website names."),
    CheckDescriptor("NET-PING", Layer.INTERNET, "Internet reachability", "Checks that the internet answers when pinged."),
    CheckDescriptor("NET-01", Layer.INTERNET, "Captive portal", "Checks whether a login page is blocking internet access."),
    CheckDescriptor("NET-03", Layer.INTERNET, "WinHTTP system proxy", "Checks the system-wide proxy setting."),
    CheckDescriptor("NET-04", Layer.INTERNET, "User (WinINET) proxy", "Checks the per-user browser proxy setting."),
    CheckDescriptor("NET-06", Layer.INTERNET, "System clock", "Checks that this PC's clock is accurate; secure sites need it."),
    CheckDescriptor("STK-01", Layer.STACK, "Winsock catalog", "Checks for third-party software hooking into Windows networking."),
    CheckDescriptor("NET-10", Layer.STACK, "TCP receive window auto-tuning", "Checks a TCP setting that affects download speed."),
)
