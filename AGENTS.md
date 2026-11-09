# AGENTS.md

Flask network dashboard. Windows is the target, with Linux/macOS command fallbacks.

### Run
- From the project dir: `.venv\Scripts\python.exe app.py` → http://127.0.0.1:5000 (binds localhost, `debug=False`, `threaded=True`).
- Project `.venv` is Python 3.14.7 with Flask 3.1 / psutil 7.2; deps are only `Flask`, `psutil` (`requirements.txt`).
- Run `app.py` as a script: imports are flat/absolute (`from config ...`, `from modules...`), not a package.
- `debug=False` means Python changes require restarting the server.

### Architecture / gotchas
- `app.py` exposes `/`, `/api/status`, `/api/devices`, `/api/diagnostics`, and `POST /api/diagnostics/<step_id>/run`. `static/js/dashboard.js` polls `/api/status` every 2000 ms (hardcoded at the bottom; `config.REFRESH_INTERVAL_MS` is unused — only `PING_TIMEOUT_SECONDS` is read).
- `modules/diagnostics.py` is a registry of predefined checks/repairs (adapter status, IP config, loopback, gateway/internet ping, DNS, traceroute, DNS flush, DHCP renew, Winsock/TCP-IP reset). Commands are argv lists — never shell strings — and the client can only select a known `step_id`; there is no arbitrary command execution. Windows-only repairs report as unsupported elsewhere. `run_diagnostic` returns `{id, success, commands, output, duration_ms}`; `list_diagnostics` returns each step's `id`, `title`, `description`, `kind`, `requires_admin`, `supported`, `available`, `command`, `reason`, `timeout`, plus `elevated` (admin detection via `IsUserAnAdmin`/`geteuid`), `system`, `check_count`, and `repair_count`.
- `BandwidthMonitor` is a module-level singleton in `app.py`; rates are deltas since the previous request, so multiple tabs or a changed poll interval distort readings. The dashboard applies EMA smoothing (`SMOOTHING_FACTOR = 0.34`) client-side before displaying or charting traffic.
- Each `/api/status` call synchronously shells out to `ping` twice (hardcoded internet host `1.1.1.1` and the detected gateway). Ping output is regex-parsed per OS.
- Device discovery first warms the ARP cache with a UDP sweep of local private subnets (max 1024 hosts, 15 s cache), then parses the OS ARP cache (`arp -a`), filtering multicast/broadcast entries. It never scans public/routed networks.
- Names resolve best-effort (NetBIOS UDP 137, then reverse DNS; 1.5 s request budget, cached 300 s positive / 60 s miss). The dashboard retries `/api/devices` once after 6 s so names cached by background workers can appear.
- Brands come from the offline OUI map in `modules/oui_vendors.py` (common-prefix subset generated from Wireshark's `manuf` data at `https://www.wireshark.org/download/automated/data/manuf`); locally administered MACs show `Private MAC`. Regenerate this data if vendor coverage is insufficient.
- The device table has five columns: name, brand, IP, MAC, entry type. `/api/devices` returns each device as `name`, `vendor`, `ip`, `mac`, and `type`.
- Device name overrides are stored client-side in `localStorage`; double-click a name to rename it.
- The device table shows up to 8 rows at a time. `DEVICE_VISIBLE_ROWS = 8` in `dashboard.js`; `applyDeviceScrollHeight()` measures the sticky `thead` plus the first 8 row heights (adding any horizontal scrollbar height) and sets `.table-wrap` max-height. It reruns after device refreshes and on window resize. `.table-wrap` has a 420px CSS fallback and `th` is sticky.
- `#device-count` shows the number of discovered devices as a pill and is updated whenever `/api/devices` renders.
- Chart.js is loaded from a CDN in `templates/index.html`, so charts need internet. `dashboard.js` calls `new Chart(...)` unguarded near the top; if the CDN fails on a fresh load, the rest of the script (devices, scroll sizing, diagnostics) never executes.
- `database/db.py` is not imported anywhere — the SQLite schema is unused scaffolding (`database/netscope.db` is gitignored).
- No tests/lint/typecheck tooling exists; verify changes manually by running the app and hitting `/api/status`, `/api/devices`, and `/api/diagnostics`.

### UI / behavior
- First `/api/devices` load can take ~2 s (0.5 s scan settle plus up to 1.5 s name resolution); later calls reuse the scan/name caches.
- The device table scrolls vertically after 8 rows and horizontally on narrow screens (`.table-wrap`, `min-width: 680px`).
- Unnamed devices are shown as `Unnamed device`; randomized/private MACs show `Private MAC` because no vendor can be determined.
- The Troubleshoot panel is a master-detail UI: `#check-steps`/`#repair-steps` render a grouped rail and `#diag-stage` renders the selected step. Per-step results are stored in `diagnosticStates` so the console shows output for the selected step. `updateDiagnosticsSummary()` drives the progress bar (`#diag-progress-fill`, `#troubleshoot-percent`). Unsupported steps stay selectable so their `reason` is visible, but their run button is disabled. Repairs prompt via `window.confirm` and warn when not elevated.
