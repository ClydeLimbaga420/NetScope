# NetScope
### Personal Network Monitoring Dashboard

NetScope is a local-first network monitoring application
built using Python and Flask.

It provides real-time network statistics, internet
connectivity checks, bandwidth monitoring, active LAN
device discovery, and guided troubleshooting.

Network troubleshooting is handled through a
step-by-step workflow. NetScope runs predefined Windows
PowerShell and Command Prompt commands on your behalf, so
common connectivity problems can be diagnosed and
repaired from the interface instead of the terminal.

## Features

- Internet connectivity monitoring
- Ping latency measurement
- Upload and download speed monitoring
- Smoothed live bandwidth charts
- Local IP address detection
- Default gateway detection
- Network adapter information
- Active local device discovery through ARP
- Automatic device names (NetBIOS / reverse DNS)
- Brand detection from MAC vendor data
- Custom device labels saved in the browser
- Device count indicator
- Eight-row device table with in-panel scrolling
- Guided network troubleshooting workflow
- Grouped diagnostic checks and repairs rail
- Progress bar with pass/fail/repair summary
- Per-step command output console
- One-click repairs (DNS flush, DHCP renew, Winsock/TCP-IP reset)
- "Run all checks" sequential diagnosis
- LAN-accessible dashboard for other devices
- Dark, responsive dashboard interface

## Technologies

- Python
- Flask
- psutil
- HTML
- CSS
- JavaScript
- Chart.js
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

pip install -r requirements.txt

### 5. Start application

python app.py

### 6. Open dashboard

On this computer:

http://127.0.0.1:5000

From another device on the same local network, use the
address printed at startup (for example
http://192.168.1.20:5000). If other devices cannot
connect, allow Python or TCP port 5000 through Windows
Firewall.

## Project Structure

NetScope/
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── AGENTS.md
├── .gitignore
│
├── modules/
│   ├── __init__.py
│   ├── network_info.py
│   ├── bandwidth.py
│   ├── ping_monitor.py
│   ├── device_scanner.py
│   ├── oui_vendors.py
│   └── diagnostics.py
│
├── database/
│   └── db.py
│
├── templates/
│   └── index.html
│
└── static/
    ├── css/
    │   └── style.css
    └── js/
        └── dashboard.js

## Important Notes

NetScope runs on your computer and binds to all network
interfaces (0.0.0.0:5000) so other devices on the same
local network can open it in a browser. The console lists
the reachable LAN addresses at startup.

There is no authentication. Anyone who can reach port
5000 can view the dashboard and trigger the predefined
troubleshooting commands on this computer, including
repairs. Use NetScope only on a trusted local network,
and never forward port 5000 to the internet.

Bandwidth monitoring measures total traffic across
network interfaces. Displayed speeds are smoothed in
the browser to reduce jitter.

Device discovery briefly probes the local private
subnet to populate the ARP cache, then reads the
operating system's ARP table. It does not scan public
or routed networks.

Device names are resolved best-effort through NetBIOS
and reverse DNS. Many devices do not publish a name.

Brands come from an offline OUI map covering common
vendors. Devices using randomized or locally
administered MAC addresses are shown as "Private MAC"
because no vendor can be determined.

Double-click a device name to save a custom label in
your browser's localStorage.

The device table shows up to eight rows at a time and
scrolls vertically to reveal the rest. The header stays
visible while scrolling, and the visible row height is
measured in the browser so it stays exact across screen
sizes.

The Troubleshoot panel runs only predefined commands
against your own computer. Checks are read-only. Repair
steps change system network settings and ask for
confirmation before running. Winsock and TCP/IP resets
require administrator rights and a restart. Each step
shows its command output in a dedicated console, and the
progress bar summarizes how many checks have passed or
failed.

Ping results may be affected by firewall rules or
network restrictions.

Chart.js is loaded through a CDN, so charts require an
internet connection. Everything else is served locally.
If the dashboard is already open, device discovery and
troubleshooting keep working without internet. On a
fresh page load with no internet, Chart.js cannot load
and the dashboard script stops early, so the device
table and troubleshooting steps may remain in their
loading state.

The SQLite schema in database/db.py is not currently
used by the application.

## Future Improvements

- mDNS/SSDP device name discovery
- Historical network statistics
- SQLite monitoring history
- Packet loss monitoring
- Per-device traffic analysis
- Device type inference
- Export device list

## License

MIT License

test 