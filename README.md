# NetScope
### Personal Network Monitoring Dashboard

NetScope is a local-first Windows network troubleshooting and monitoring
application. It provides real-time network statistics, internet connectivity
checks, bandwidth monitoring, active LAN device discovery, and guided
troubleshooting.

A single shared diagnostic engine powers three front ends: a command-line
interface, a desktop GUI, and a localhost web UI. Diagnostics run predefined
Windows PowerShell and Command Prompt checks across the adapter, services, IP,
gateway, LAN, DNS, internet, and protocol stack layers. Failed checks link to a
catalogued repair that can be previewed, dry-run, executed with confirmation,
verified by re-checking, and rolled back from a pre-fix snapshot.

The legacy Flask dashboard (`python app.py`) remains available for LAN access
while the localhost web UI replaces it.

## Features

### Diagnostics and fixes
- Engine-backed diagnosis across eight network layers
- 61-entry fix catalog with exact-command preview and dry-run
- Admin, risk, and reboot labels; typed confirmation for high-risk steps
- Verification by re-checking and rollback from saved snapshots
- Unresolved-cause ranking when a fix does not help ("probable"/"possible")
- Repair library with plain-language steps and collapsible exact commands
- One-click **Run as administrator** (UAC) for admin-only repairs
- Structured JSON-lines logging with secrets redacted

### Interfaces
- CLI with `diagnose`, `fix`, `info`, `ping`, `trace`, `dns`, `arp`, `routes`,
  `ports`, `mtu`, `monitor`, `logs`, `report`, and `gui`
- Interactive `netscope>` shell with history, completion, and a numbered menu
- Desktop GUI with findings detail, fix preview, and unresolved-causes panel
- Localhost web UI with per-check streaming, a repair library, and local assets
- Legacy LAN dashboard for other devices on the same network

### Dashboard
- Internet connectivity and ping latency monitoring
- Smoothed live bandwidth charts
- Local IP, default gateway, and adapter information
- Active device discovery through ARP
- Automatic device names (NetBIOS / reverse DNS)
- Brand detection from MAC vendor data and randomized-MAC labelling
- Custom device labels saved in the browser
- Eight-row device table with in-panel scrolling
- Guided troubleshooting workflow with grouped checks and repairs

## Technologies

- Python
- PowerShell (Windows PowerShell 5.1)
- Flask, Werkzeug, and Jinja2
- psutil
- HTML, CSS, and JavaScript
- Chart.js (bundled locally)
- pytest
- SQLite (schema present, not yet used)

## Installation

### 1. Clone the repository

git clone https://github.com/yourusername/NetScope.git

cd NetScope

### 2. Create virtual environment

py -m venv .venv

### 3. Activate environment

.venv\Scripts\activate

### 4. Install dependencies

pip install -r requirements.txt -r requirements-dev.txt

### 5. Run NetScope

Command line:

python netscope.py --help

python netscope.py diagnose

Localhost web UI:

python netscope.py gui

Use `python netscope.py gui --no-browser --port N` to run it in the foreground
and print its boot URL. The web UI binds only to `127.0.0.1`.

Legacy LAN dashboard:

python app.py

then open http://127.0.0.1:5000 locally, or
`http://<LAN-IP>:5000` from another device. If other devices cannot connect,
allow Python or TCP port 5000 through Windows Firewall.

### 6. Run tests

python -m pytest

## Project Structure

NetScope/
├── netscope.py          # CLI entry point
├── app.py               # legacy Flask LAN dashboard
├── config.py
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── AGENTS.md
├── task.md
│
├── core/                # shared engine, models, runner, snapshot, checks
├── powershell/          # static PS scripts, runner, input validation
├── fixes/               # catalog, executor, unresolved-cause ranking
├── cli/                 # parser, dispatch, rendering, utilities, shell, monitor
├── gui/                 # tkinter front end
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
- Packet loss monitoring
- Per-device traffic analysis
- Device type inference
- Export device list
- Packaged executable, installer, and GitHub Actions CI

## License

MIT License
