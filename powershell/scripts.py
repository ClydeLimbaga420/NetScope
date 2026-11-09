"""Static PowerShell query fragments used by NetScope.

Every fragment is a PowerShell *expression* that returns objects. Nothing in
this module interpolates user input; parameterised fix scripts live in the fix
catalog (Phase 3) and receive values through ``-ParamName value`` arguments.
"""

from __future__ import annotations

ADAPTERS = (
    "Get-NetAdapter -ErrorAction SilentlyContinue | "
    "Select-Object Name,InterfaceAlias,InterfaceDescription,Status,LinkSpeed,"
    "MacAddress,ifIndex,MediaType,PhysicalMediaType,Virtual,ConnectorPresent"
)

IP_ADDRESSES = (
    "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
    "Select-Object IPAddress,PrefixLength,PrefixOrigin,SuffixOrigin,AddressState,"
    "InterfaceAlias,InterfaceIndex,ValidLifetime,PreferredLifetime"
)

IP_CONFIGURATION = (
    "Get-NetIPConfiguration -ErrorAction SilentlyContinue | "
    "Select-Object InterfaceAlias,InterfaceIndex,"
    "@{n='IPv4Address';e={$_.IPv4Address.IPAddress}},"
    "@{n='PrefixLength';e={$_.IPv4Address.PrefixLength}},"
    "@{n='IPv4Gateway';e={$_.IPv4DefaultGateway.NextHop}},"
    "@{n='IPv6Address';e={$_.IPv6Address.IPAddress}},"
    "@{n='IPv6Gateway';e={$_.IPv6DefaultGateway.NextHop}},"
    "@{n='DnsServers';e={$_.DNSServer.ServerAddresses}}"
)

ROUTES = (
    "Get-NetRoute -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
    "Select-Object DestinationPrefix,NextHop,InterfaceAlias,InterfaceIndex,"
    "RouteMetric,InterfaceMetric,Store,Protocol"
)

NEIGHBORS = (
    "Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
    "Select-Object IPAddress,LinkLayerAddress,State,InterfaceAlias,InterfaceIndex,"
    "PolicyStore"
)

DNS_SERVERS = (
    "Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
    "Select-Object InterfaceAlias,InterfaceIndex,"
    "@{n='ServerAddresses';e={$_.ServerAddresses}}"
)

SERVICES = (
    "Get-CimInstance -ClassName Win32_Service -ErrorAction SilentlyContinue | "
    "Where-Object { $_.Name -in @('WlanSvc','Dhcp','Dnscache','NlaSvc','netprofm',"
    "'BFE','LanmanServer','LanmanWorkstation','FDResPub','SSDPSRV','upnphost') } | "
    "Select-Object Name,DisplayName,State,StartMode,Status"
)

PNP_NETWORK_DEVICES = (
    "Get-PnpDevice -Class Net -ErrorAction SilentlyContinue | "
    "Select-Object FriendlyName,Status,Problem,ProblemDescription,InstanceId"
)

ADAPTER_POWER = (
    "Get-NetAdapterPowerManagement -ErrorAction SilentlyContinue | "
    "Select-Object Name,AllowComputerToTurnOffDevice"
)

ADAPTER_STATISTICS = (
    "Get-NetAdapterStatistics -ErrorAction SilentlyContinue | "
    "Select-Object Name,ReceivedBytes,ReceivedUnicastPackets,"
    "ReceivedDiscardedPackets,ReceivedPacketErrors,"
    "SentBytes,SentUnicastPackets,SentDiscardedPackets,OutboundPacketErrors"
)

CONNECTION_PROFILES = (
    "Get-NetConnectionProfile -ErrorAction SilentlyContinue | "
    "Select-Object Name,InterfaceAlias,InterfaceIndex,NetworkCategory,"
    "IPv4Connectivity,IPv6Connectivity"
)

FIREWALL_PROFILES = (
    "Get-NetFirewallProfile -ErrorAction SilentlyContinue | "
    "Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction"
)

FIREWALL_DISCOVERY_RULES = (
    "Get-NetFirewallRule -ErrorAction SilentlyContinue | "
    "Where-Object { $_.Group -in @('@FirewallAPI.dll,-32752','@FirewallAPI.dll,-28502') } | "
    "Select-Object Group,DisplayGroup,DisplayName,Enabled,Direction,Action,Profile"
)

SMB_CLIENT = (
    "Get-SmbClientConfiguration -ErrorAction SilentlyContinue | "
    "Select-Object EnableSMB2Protocol,RequireSecuritySignature,EnableSecuritySignature"
)

SYSTEM_PROXY = (
    "Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
    "-ErrorAction SilentlyContinue | "
    "Select-Object ProxyEnable,ProxyServer,ProxyOverride,AutoConfigURL"
)

NCSI_SETTINGS = (
    "Get-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\NlaSvc\\Parameters\\Internet' "
    "-ErrorAction SilentlyContinue | "
    "Select-Object EnableActiveProbing,ActiveWebProbeHost,ActiveWebProbePath"
)

WINSOCK_LSP = (
    "Get-ChildItem "
    "'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\WinSock2\\Parameters\\"
    "Protocol_Catalog9\\Catalog_Entries' -ErrorAction SilentlyContinue | "
    "ForEach-Object { "
    "(Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).PackedCatalogItem "
    "}"
)

VPN_CONNECTIONS = (
    "Get-VpnConnection -ErrorAction SilentlyContinue | "
    "Select-Object Name,ServerAddress,TunnelType,ConnectionStatus,SplitTunneling,"
    "DnsSuffix,InterfaceIndex"
)

LANGUAGE_MODE = "$ExecutionContext.SessionState.LanguageMode"

# Queries that can be combined into one PowerShell startup without taking
# parameters. The key is the snapshot section name.
BATCH_QUERIES: dict[str, str] = {
    "adapters": ADAPTERS,
    "ip_addresses": IP_ADDRESSES,
    "ip_configuration": IP_CONFIGURATION,
    "routes": ROUTES,
    "neighbors": NEIGHBORS,
    "dns_servers": DNS_SERVERS,
    "services": SERVICES,
    "pnp_network_devices": PNP_NETWORK_DEVICES,
    "adapter_power": ADAPTER_POWER,
    "adapter_statistics": ADAPTER_STATISTICS,
    "connection_profiles": CONNECTION_PROFILES,
    "firewall_profiles": FIREWALL_PROFILES,
    "firewall_discovery_rules": FIREWALL_DISCOVERY_RULES,
    "smb_client": SMB_CLIENT,
    "system_proxy": SYSTEM_PROXY,
    "ncsi_settings": NCSI_SETTINGS,
    "vpn_connections": VPN_CONNECTIONS,
}

# Native executables used when a cmdlet is missing or PowerShell is blocked.
NATIVE_FALLBACKS: dict[str, list[str]] = {
    "adapters": ["ipconfig", "/all"],
    "routes": ["route", "print"],
    "neighbors": ["arp", "-a"],
    "services": ["sc", "query"],
    "dns_servers": ["ipconfig", "/all"],
    "winsock": ["netsh", "winsock", "show", "catalog"],
    "tcp_global": ["netsh", "int", "tcp", "show", "global"],
}
