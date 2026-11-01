# NetScope
### Personal Network Monitoring Dashboard

NetScope is a local-first network monitoring application
built using Python and Flask.

It provides real-time network statistics, internet
connectivity checks, bandwidth monitoring, and active
LAN device discovery.

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

http://127.0.0.1:5000

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

NetScope runs locally on your computer and binds to
127.0.0.1 by default.

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

Ping results may be affected by firewall rules or
network restrictions.

Chart.js is loaded through a CDN, so charts require
an internet connection.

The SQLite schema in database/db.py is not currently
used by the application.

## Future Improvements

- mDNS/SSDP device name discovery
- Historical network statistics
- SQLite monitoring history
- DNS diagnostics
- Traceroute
- Packet loss monitoring
- Per-device traffic analysis
- Device type inference
- Export device list

## License

MIT License
