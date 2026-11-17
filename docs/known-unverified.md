# Known-unverified paths and Windows 10 vs 11 differences

This project was developed and validated primarily on Windows 11 (build 26200)
with Windows PowerShell 5.1 and Python 3.14. The items below are either not
covered by automated tests or depend on OS/locale behaviour that differs between
Windows 10 and Windows 11. Treat them as manual-verification targets, not as
guarantees.

## Catalog repairs flagged `[VERIFY]`

These entries pass schema validation and have preview/rollback data, but their
exact commands have not been validated end-to-end on both Windows versions:

| Fix | Area | Why it is flagged |
| --- | --- | --- |
| `IP-08` | Static IP / gateway | `netsh` parameter names and adapter aliases vary by locale and driver |
| `LAN-10` | Network profile / discovery | Firewall group display names are localized |
| `DNS-04` | DNS client configuration | Interface index and `Set-DnsClientServerAddress` shape vary |
| `DNS-05` | DNS cache / resolver reset | Service restart and flush ordering on older builds |
| `NET-06` | Winsock / TCP-IP reset | Requires a reboot; post-reboot state is not re-checked automatically |
| `NET-08` | Firewall profile reset | Localized profile/group names and policy merge behaviour |
| `NET-11` | Route / interface reset | Persistent routes and interface metrics differ |

`LAN-09` is intentionally DETECT-ONLY. The original specification suggested an
optional `AllowInsecureGuestAuth=1` registry change; NetScope does not script
that setting because it weakens SMB guest security.

## Windows 10 vs Windows 11 differences

| Area | Windows 10 | Windows 11 | Impact |
| --- | --- | --- | --- |
| `Get-NetAdapter` properties | Older builds omit or rename some properties (`MediaConnectionState`, link-speed fields) | More consistent, but still localized | Adapter checks use defensive defaults; low-speed/driver checks may skip |
| Wi-Fi direct / virtual adapters | `Local Area Connection*` and Microsoft Wi-Fi Direct names | Same idea, different per-driver naming | Virtual adapters are excluded by pattern, not by a fixed list |
| Firewall groups | Localized display names; group membership differs | Localized and reorganized | Discovery/firewall checks may warn on a different group than expected |
| `netsh` output | Localized headings and spacing | Localized headings and spacing | Native parsers use tolerant regexes; some columns may be missed on non-English builds |
| IPv6 gateway output | `ipconfig` may wrap the IPv4 gateway onto the next line | Same, but layout can differ | `_windows_default_gateway()` handles continuation lines; verify on the target build |
| NCSI / captive portal | `www.msftconnecttest.com` | Same endpoint generally | Corporate proxies can rewrite or block the endpoint |
| PowerShell language mode | Constrained Language under AppLocker/WDAC | Same mechanism, different policy defaults | The layer reports `ConstrainedLanguage`; native fallbacks are used where available |
| Start Menu path | `%APPDATA%\Microsoft\Windows\Start Menu\Programs` | Same | Shortcut creation is user-scoped |
| App-style browser window | Edge/Chrome `--app` support varies by version | Edge is usually present | Falls back to the default browser; launch failures print the URL |
| UAC relaunch | Standard token behaviour | Same, but Windows 11 may show additional prompts | Admin-only fixes report exit 4 and the exact command instead of escalating silently |
| Reboot-required repairs | Winsock/TCP-IP resets | Same commands | Verification cannot prove the post-reboot state; the result says a restart is required |
| ARM64 | Not tested | Not tested | The current artifact is x64 only |

## Not verified in this repository

- Real Windows 10 end-to-end runs (all eight layers, every repair).
- Non-English Windows UI/locale output for `ping`, `ipconfig`, `netsh`, `arp`,
  `route`, and `Get-Net*`.
- Wi-Fi roaming, captive portals, VPN split tunneling, and metered connections.
- Corporate proxy authentication and PAC/WPAD discovery beyond the read-only
  proxy checks.
- Windows Server SKUs, Windows Sandbox, and domain-managed Group Policy.
- Long-running bandwidth/monitor accuracy across sleep/resume and adapter
  changes.
- Frozen build on a clean machine with no Python installed (the smoke test runs
  on the build host).
- Installer when `HKCU\Environment\Path` is near the legacy 2048-character
  limit or contains malformed entries.
- Shortcut creation when the Start Menu folder is redirected by policy.
- Browser app-mode launch for browsers other than Edge/Chrome; the fallback
  opens the default browser.
- UAC decline/consent races during `/api/elevate`.
- Screen readers and high-contrast mode on the web UI; reduced-motion styling
  is present but not audited with assistive technology.

## Compatibility notes for maintainers

- The exe is windowed-subsystem: a double-click shows no console at all. CLI
  output from a terminal is restored with `AttachConsole(ATTACH_PARENT_PROCESS)`.
- `fixes/catalog.py` validates catalog text at load time. Adding a repair with a
  new parameter source or validator requires updating both the validator and
  the executor, plus a test.
- `web/paths.py` resolves templates/static through `sys._MEIPASS`. New bundled
  data files must be added to `NetScope.spec` and to the offline asset tests.
- The legacy `app.py` dashboard is still unauthenticated and LAN-bound. Do not
  expose it to the internet; the localhost web UI is the supported interface.
