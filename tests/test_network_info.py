from modules.network_info import _windows_default_gateway


IPCONFIG = """
Windows IP Configuration


Ethernet adapter Ethernet 2:

   IPv4 Address. . . . . . . . . . . : 192.168.56.1
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . :

Ethernet adapter Ethernet:

   IPv4 Address. . . . . . . . . . . : 192.168.254.143
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : fe80::1%13
                                       192.168.254.254
"""


def test_windows_gateway_skips_ipv6_and_reads_continuation_line():
    assert _windows_default_gateway(IPCONFIG) == "192.168.254.254"


def test_windows_gateway_reads_inline_ipv4():
    output = (
        "   Default Gateway . . . . . . . . . : 10.0.0.1\n"
        "   DNS Servers . . . . . . . . . . . : 10.0.0.2\n"
    )

    assert _windows_default_gateway(output) == "10.0.0.1"


def test_windows_gateway_ignores_unspecified_address():
    output = "   Default Gateway . . . . . . . . . : 0.0.0.0\n"

    assert _windows_default_gateway(output) is None
