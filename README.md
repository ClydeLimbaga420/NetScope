# NetScope
### Personal Network Monitoring Dashboard

NetScope is a local-first Windows network troubleshooting and monitoring
application. It provides real-time network statistics, internet connectivity
checks, bandwidth monitoring, active LAN device discovery, and guided
troubleshooting.

A single shared diagnostic engine powers two front ends: a command-line
interface and a localhost web UI. Diagnostics run predefined Windows PowerShell
and Command Prompt checks across the adapter, services, IP, gateway, LAN, DNS,
internet, and protocol stack layers. Failed checks link to a catalogued repair
that can be previewed, dry-run, executed with confirmation, verified by
re-checking, and rolled back from a pre-fix snapshot.

The web UI replaces the former tkinter desktop GUI. The legacy Flask dashboard
(`python app.py`) remains available for LAN access only.

## Features

### Diagnostics and fixes
- Engine-backed diagnosis across eight network layers
- 62-entry fix catalog with exact-command preview and dry-run
- Automatic default-gateway detection and one-click configuration (`IP-09`)
- Admin, risk, and reboot labels; typed confirmation for high-risk steps
- Verification by re-checking and rollback from saved snapshots
- Unresolved-cause ranking when a fix does not help ("probable"/"possible")
- Repair library with plain-language steps and collapsible exact commands
- One-click **Run as administrator** (UAC) for admin-only repairs
- Structured JSON-lines logging with secrets redacted

### Interfaces
- CLI with `diagnose`, `fix`, `info`, `ping`, `trace`, `dns`, `arp`, `routes`,
  `ports`, `mtu`, `monitor`, `logs`, `report`, `gui`, `install`, and `uninstall`
- Interactive `netscope>` shell with history, completion, and a numbered menu
- Localhost web UI with per-check streaming, a repair library, and local assets
- Per-user installer with PATH, App Paths, and Start Menu integration
- Legacy LAN dashboard for other devices on the same network
- Separate engine-backed Run diagnosis action in the web UI
- Per-step Run buttons on every diagnostics and repair item

### Dashboard
- Combined Internet and Gateway connectivity status card
- Internet connectivity and ping latency monitoring
- Packet loss monitoring for internet and gateway pings
- Smoothed live bandwidth charts
- Local IP, default gateway, and adapter information
- Active device discovery through ARP
- Automatic device names (NetBIOS / reverse DNS)
- Brand detection from MAC vendor data and randomized-MAC labelling
- Custom device labels saved in the browser
- Eight-row device table with in-panel scrolling
- Guided troubleshooting workflow with grouped checks and repairs
- Run buttons on every diagnostic and repair item
- Simple descriptions under each diagnostics title
- Animated running state on in-progress checks
- One-click Configure gateway button when no default gateway is detected
- Separate engine-backed Run diagnosis action in the web UI

## Technologies

- Python
- PowerShell (Windows PowerShell 5.1)
- Flask, Werkzeug, and Jinja2
- psutil
- HTML, CSS, and JavaScript
- Chart.js (bundled locally)
- pytest
- PyInstaller
- GitHub Actions
- SQLite (schema present, not yet used)

## Installation

### Option A - prebuilt executable (recommended)

Build `dist\NetScope.exe` (see [Building the executable](#building-the-executable))
or download it from a release, then install it for the current user:

```
NetScope.exe install
```

This copies the exe to `%LOCALAPPDATA%\Programs\NetScope\`, adds that directory
to your user `PATH`, registers it in `App Paths`, creates a Start Menu shortcut,
and broadcasts the environment change. Open a new terminal afterwards. Use
`NetScope.exe install --dry-run` to preview, `--source PATH` for a different exe,
`--dir PATH` for a different install directory, or `--no-shortcut` to skip the
Start Menu entry. Non-interactive installs require `--yes`.

After installation:

```
NetScope.exe            # double-click / Win+R: opens the web UI
netscope gui            # terminal: background server + browser
netscope diagnose       # terminal: CLI diagnosis
```

Remove it with `NetScope.exe uninstall`, or `NetScope.exe uninstall --purge`
to also delete `%LOCALAPPDATA%\NetScope` (logs, reports, and fix backups).

### Option B - from source

#### 1. Clone the repository

git clone https://github.com/yourusername/NetScope.git

cd NetScope

#### 2. Create virtual environment

py -m venv .venv

#### 3. Activate environment

.venv\Scripts\activate

#### 4. Install dependencies

```
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

#### 5. Run NetScope

Command line:

```
netscope --help
netscope diagnose
```

Localhost web UI:

```
netscope gui
```

Use `netscope gui --no-browser --port N` to run it in the foreground and print
its boot URL. The web UI binds only to `127.0.0.1`.

Legacy LAN dashboard:

```
python app.py
```

then open http://127.0.0.1:5000 locally, or
`http://<LAN-IP>:5000` from another device. If other devices cannot connect,
allow Python or TCP port 5000 through Windows Firewall.

#### 6. Run tests

```
.\.venv\Scripts\python.exe -m pytest
```

## Project Structure

NetScope/
├── netscope.py          # CLI entry point
├── NetScope.spec        # PyInstaller one-file build definition
├── app.py               # legacy Flask LAN dashboard
├── config.py
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── AGENTS.md
├── task.md
│
├── .github/workflows/   # windows-latest test + build CI
├── scripts/             # build.ps1 and frozen-exe smoke test
├── core/                # shared engine, models, runner, snapshot, checks
├── powershell/          # static PS scripts, runner, input validation
├── fixes/               # catalog, executor, unresolved-cause ranking
├── cli/                 # parser, dispatch, rendering, utilities, shell, monitor
├── web/                 # localhost server, API, jobs/SSE, security, templates
├── modules/             # legacy dashboard modules
├── templates/           # legacy dashboard template
├── static/              # legacy dashboard assets and bundled Chart.js/fonts
├── database/
└── tests/

## Important Notes

NetScope changes system network settings only through catalogued repairs. Every
command runs without a shell, user input is validated before it reaches a
command, and every command has a timeout. State is recorded before a fix so it
can be rolled back.

The localhost web UI binds to `127.0.0.1` and uses boot/session tokens,
same-origin checks for state-changing requests, a Content Security Policy, and
security headers. It is not exposed to the LAN.

The legacy dashboard (`python app.py`) binds to all network interfaces
(`0.0.0.0:5000`) so other LAN devices can open it. It has no authentication:
anyone who can reach port 5000 can view the dashboard and trigger predefined
troubleshooting commands, including repairs. Use it only on a trusted local
network, and never forward port 5000 to the internet.

Bandwidth monitoring measures total traffic across network interfaces.
Displayed speeds are smoothed in the browser to reduce jitter.

Device discovery briefly probes the local private subnet to populate the ARP
cache, then reads the operating system's ARP table. It does not scan public or
routed networks.

Device names are resolved best-effort through NetBIOS and reverse DNS. Many
devices do not publish a name.

Brands come from an offline OUI map covering common vendors. Devices using
randomized or locally administered MAC addresses are shown as "Private MAC"
because no vendor can be determined.

Double-click a device name to save a custom label in your browser's
localStorage.

The device table shows up to eight rows at a time and scrolls vertically to
reveal the rest. The header stays visible while scrolling, and the visible row
height is measured in the browser so it stays exact across screen sizes.

The Troubleshoot panel runs only predefined commands against your own computer.
Checks are read-only. Repair steps change system network settings and ask for
confirmation before running. Winsock and TCP/IP resets require administrator
rights and a restart.

Chart.js and the interface fonts are bundled locally, so the dashboard does not
depend on a CDN or an internet connection to load.

The SQLite schema in database/db.py is not currently used by the application.

## Future Improvements

- mDNS/SSDP device name discovery
- Historical network statistics
- SQLite monitoring history
- Per-device traffic analysis
- Device type inference
- Export device list

## Running

### One-time dev setup (creates the `netscope` command)

```bash
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

After that, just type `netscope` from any shell:

```bash
netscope --help
netscope diagnose
netscope gui
netscope info
```

### From source (without editable install)

```bash
python app.py                    # legacy Flask dashboard on http://127.0.0.1:5000
.\.venv\Scripts\python.exe netscope.py --help
.\.venv\Scripts\python.exe netscope.py gui
```

## CLI reference

Global flags work before or after the subcommand: `--json`, `--no-color`,
`--quiet`/`-q`, `--verbose`/`-v`, `--yes`/`-y`, `--dry-run`,
`--yes-i-understand-risk`, `--version`.

| Command | Purpose | Key options |
| --- | --- | --- |
| `diagnose` | Run the layered pipeline | `--layer adapter,services,ip,gateway,lan,dns,internet,stack` (repeatable) |
| `fix` | Preview, execute, verify, or roll back a catalog fix | `finding`/fix id, `--rollback`, `--adapter`, `--target`, `--value`, `--param NAME=VALUE` |
| `info` | Adapters, addressing, routes, ARP, DNS, proxy, VPN, Wi-Fi, MTU | `--adapter NAME` |
| `ping` | ICMP reachability | `--count`, `--timeout` |
| `trace` | Route trace | `--max-hops`, `--timeout` |
| `dns` | Resolve a name | `--server IP` |
| `arp` | ARP table | |
| `routes` | IPv4 route table | |
| `ports` | TCP port reachability (max 1024 ports) | `host 80,443,8000-8100` |
| `mtu` | Path MTU probe (DF pings, 548-1472 payload) | `host` |
| `monitor` | Live ANSI dashboard | `--interval SECONDS` |
| `logs` | View/open/export the JSON-lines log | `--tail`, `--open`, `--export FILE` |
| `report` | Save a diagnostic report | `--format txt\|json`, `--output FILE` (`-` = stdout) |
| `gui` | Start the localhost web UI | `--no-browser`, `--port N` |
| `install` | Install for the current user | `--source FILE`, `--dir DIR`, `--no-shortcut` |
| `uninstall` | Remove the current-user install | `--dir DIR`, `--purge` |

Running `netscope` with no arguments in a terminal opens the interactive
`netscope>` shell (`help`, numbered `menu`, `monitor`, `exit`).

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | All checks passed or were skipped |
| 1 | Warnings remain |
| 2 | Failures remain (including an unresolved fix) |
| 3 | A fix failed |
| 4 | Administrator privileges are required |
| 64 | Usage error |
| 130 | Interrupted with Ctrl+C |

`diagnose --json` and the other `--json` commands emit one machine-readable
document on stdout; progress and errors stay on stderr. Non-interactive use
never prompts: pass `--yes` where confirmation is needed.

## Building the executable

The one-file, console-subsystem build bundles the web templates/static files and
the fix catalog:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Clean
python scripts\frozen_smoke.py --exe dist\NetScope.exe
```

To put the executable in the repository root instead of `dist\`, use
`-DistPath .`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Clean -DistPath .
```

`scripts\build.ps1` uses `.venv\Scripts\python.exe` when present and requires
PyInstaller (`pip install pyinstaller`). The current build is about 13.8 MB on
Python 3.14.7 / PyInstaller 6.22.3. `NetScope.spec` excludes tkinter and unused
GUI/scientific packages, and `web/paths.py` resolves bundled assets through
`sys._MEIPASS`.

The exe intentionally stays console-subsystem so the CLI works from any
terminal. Double-clicking it briefly flashes a console before the GUI child
detaches; `netscope gui` from a terminal detaches immediately and returns the
prompt. A terminal with no arguments still opens the `netscope>` shell.

## Install and uninstall

The installer is per-user and requires no elevation:

- copies `NetScope.exe` to `%LOCALAPPDATA%\Programs\NetScope\`
- adds that directory to `HKCU\Environment\Path` (preserving the raw value type)
- registers `HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths\NetScope.exe`
- creates `%APPDATA%\Microsoft\Windows\Start Menu\Programs\NetScope.lnk`
- broadcasts `WM_SETTINGCHANGE` and writes a `.netscope-install` marker

Uninstall removes exactly those entries and the marked install directory. It
never deletes unrelated files. User data in `%LOCALAPPDATA%\NetScope` (logs,
reports, fix backups) is kept unless `--purge` is passed. Both commands support
`--dry-run` and require `--yes` when stdin is not a terminal.

## Dual-mode launch

| Situation | Behaviour |
| --- | --- |
| Double-click `NetScope.exe`, Win+R, Start Menu | Detach/hide the console, start the localhost server, open the app window |
| `netscope gui` in a terminal | Start a detached server and return to the prompt |
| `netscope gui --no-browser --port N` | Run in the foreground and print the boot URL |
| `netscope` / `NetScope.exe` with no args in a terminal | Interactive `netscope>` shell |
| `netscope diagnose`, `fix`, `info`, ... | Normal CLI output |

Only one web UI runs per user. A second launch waits for the owner to publish
its endpoint, verifies `/health`, and reopens the existing instance. The server
shuts down on `POST /api/shutdown`, on Ctrl+C, or after the browser heartbeat
has been absent for 120 seconds with no active job or fix running.

## Web UI and API

The web UI binds to `127.0.0.1` only. A boot token is exchanged for an HttpOnly,
SameSite=Strict session cookie; state-changing requests additionally require
`X-NetScope-Token` and a same-origin `Origin`/`Referer`. Responses carry a
strict CSP and security headers. Assets (CSS, JS, Chart.js, fonts) are bundled
locally, so the UI works offline and needs no CDN.

The JSON API is a thin layer over the same engine/catalog/utilities as the CLI:
`/api/status`, `/api/checks`, `/api/diagnose`, `/api/jobs/<id>` (+ `/events`,
`/cancel`), `/api/findings`, `/api/fix/plan`, `/api/fix/execute`,
`/api/fix/rollback`, `/api/fix/history`, `/api/fixes`,
`/api/unresolved/answer`, `/api/info`, `/api/tools/<name>`, `/api/logs`,
`/api/logs/stream`, `/api/report`, `/api/devices`, `/api/heartbeat`,
`/api/shutdown`, and `/api/elevate`. Long operations run as background jobs and
stream over Server-Sent Events with polling fallback.

The legacy dashboard (`python app.py`) is separate and unauthenticated. Keep it
on a trusted LAN and never expose port 5000 to the internet.

## Adding checks, fixes, and subcommands

- **Checks**: add the logic to `core/checks/<layer>.py` as `run(ctx) ->
  list[CheckResult]`, keep the layer order in `core/models.py`, and add the
  planned check to `core/checks/descriptors.py` so the web rail lists it.
  Return structured `evidence` and a `cause`; never raise for expected network
  failures (the engine captures exceptions as `ERROR`). Add a case to
  `tests/test_checks.py` using the `snapshot_factory` fixture.
- **Fixes**: add or edit an entry in `fixes/fixes.json` (id, symptom,
  detection, explanation, admin/risk/reboot, snapshot, rollback, verify,
  ladder, if_unresolved). Commands are argv lists or static PowerShell text;
  user values are separate parameters. `fixes/catalog.py` validates IDs,
  parameter sources, `$Param` declarations, high-risk second confirmation, and
  DETECT-ONLY restrictions. Run `tests/test_fixes.py`.
- **Subcommands**: add the parser in `cli/parser.py`, a `cmd_<name>` handler in
  `cli/commands.py`, and register it in `HANDLERS`. Keep rendering in `cli/`
  and detection/fix logic in `core/`/`fixes/`. `--json` must emit one document.
- **Web routes**: add the endpoint to `web/api.py` over an existing core/fix
  call; do not put diagnostic logic in the web layer. Update
  `tests/test_web_api.py` and `tests/test_web_design.py` when markup/assets
  change.

## [VERIFY] repairs and known limitations

These catalog repairs are included but flagged `[VERIFY]`: their commands have
not been validated end-to-end on both Windows 10 and Windows 11 in this project.
Review the exact commands before applying them.

`IP-08`, `LAN-10`, `DNS-04`, `DNS-05`, `NET-06`, `NET-08`, `NET-11`

`LAN-09` is deliberately DETECT-ONLY. The original specification suggested an
optional `AllowInsecureGuestAuth=1` registry change; NetScope does not script
that unsafe setting. See [docs/known-unverified.md](docs/known-unverified.md)
for the remaining Win10/Win11 differences and unverified paths.

## Testing on a Windows VM

Use [docs/manual-test-checklist.md](docs/manual-test-checklist.md) for failure
simulation: disable the adapter, unplug the cable, use a wrong static IP, stop
Dnscache, blackhole DNS, block the gateway, and trigger an unfixable upstream
outage to exercise the unresolved panel. CI runs the same suite on
`windows-latest` only when `main` is updated (push or merge), runs a Playwright
headless-browser smoke test (skipped if no Chromium/Edge is available), builds
the exe, and runs the frozen smoke test.

The Phase D/E packaging, installer, and CI report is in
[docs/phaseDE-report.md](docs/phaseDE-report.md); the close-out artifact index
is [docs/phaseE-deliverables.md](docs/phaseE-deliverables.md).

## License

MIT License

