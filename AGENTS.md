# AGENTS.md

NetScope is a universal Windows network troubleshooting tool with one shared
engine and two front ends (CLI + localhost web UI). Work phase by phase; update
this file and `task.md` Notes at the end of every phase.

**Current status: Phase 5, Phase 6 D/E, the Phase 7 desktop-installer follow-up,
and the single-executable GUI-launch/window-fit follow-up are complete.**
tkinter is removed. `dist/NetScope.exe` is a one-file
windowed-subsystem build (19.8 MB) bundling web templates/static, the fix
catalog, pywebview/WebView2 and pythonnet; `dist/installer/NetScope-Setup.exe`
(21.6 MB, Inno Setup 6.7.3) is a per-user installer with PATH/App Paths/Start
Menu/desktop shortcuts, uninstaller, WebView2 handling, and a `.netscope-inno`
marker. `netscope install`/`uninstall` still manage portable installs and refuse
installer-managed copies. CI covers tests on Python 3.11/3.14, 80% coverage,
Playwright browser smoke + screenshots, frozen exe smoke, and an Inno
install/uninstall smoke. Latest local suite: 439 passed, 3 skipped (2026-11-20);
coverage 83.11% over `core`/`fixes`/`powershell`.
Manual validation (Windows 10
VM checklist, window/UAC/installer cases, and human screenshot review) is
deferred for now by request; it is a release-confidence item, not a code or
test blocker. Phase 7 and GUI launch follow-up changes are committed locally;
remote CI has not been run.

**Low-end-device / request-storm follow-up (2026-11-18):** `config.py` now owns
env-overridable resource caps (`NETSCOPE_MAX_CONCURRENT_COMMANDS` = 8,
`NETSCOPE_SCAN_MAX_HOSTS` = 256, `NETSCOPE_SCAN_MAX_WORKERS` = 8,
`NETSCOPE_NAME_MAX_WORKERS` = 4, `NETSCOPE_SCAN_CACHE_SECONDS` = 60,
`NETSCOPE_NAME_CACHE_SECONDS` = 600, `NETSCOPE_SNAPSHOT_CACHE_SECONDS` = 30,
`NETSCOPE_DEVICE_CACHE_SECONDS` = 60, `NETSCOPE_PACKET_LOSS_CACHE_SECONDS` = 60,
`NETSCOPE_MAX_REMOTE_PINGS` = 2). `core/runner.py` enforces one global bounded
semaphore around `SubprocessRunner` child processes (cancel-aware while waiting),
so bursts from discovery, monitoring and UI routes cannot spawn unbounded
commands. `core/device_discovery.py` uses the smaller caps and an IP+MAC name
cache (positive TTL 600s, negative 120s) so repeated refreshes stop re-running
NetBIOS/`ping -a`/DNS. `core/monitoring.py` uses the longer cache windows and
`core/snapshot.py` caps remote-LAN pings. `web/api.py` has a serialized
`_shared_snapshot(st)` helper: `/api/info`, `/api/report` and `/api/fix/plan`
reuse `st.last_snapshot` or the monitoring snapshot instead of each starting a
full collection; the diagnose job still forces one fresh collection but does so
under the same lock, so concurrent jobs cannot double-spawn. `dashboard.js`
skips status/packet-loss polls in hidden tabs, refreshes both on
`visibilitychange`, and samples packet loss every 60s. Focused tests: 125 passed; `node --check` clean; full suite: 366 passed,
3 skipped; coverage 83.67%. Crash reproduction on the user's low-end machine
and a slow-machine timing check remain manual validation items.

**Log-overload follow-up (2026-11-19):** `config.LOG_CLEAR_INTERVAL_SECONDS`
(default 180, `NETSCOPE_LOG_CLEAR_INTERVAL_SECONDS`, 0 disables) drives a daemon
cleanup thread started by `web/run.py` for the server lifetime.
`core/logging_config.py` owns `clear_logs()` (truncates the active log under the
`RotatingFileHandler` lock so the live stream keeps writing at offset 0, and
deletes rotated backups) and `start_log_cleanup()` (stops on shutdown).
`/api/logs` reads a bounded `deque` tail rather than the whole file, and the
Troubleshoot log view auto-refreshes every 30 seconds while open. Switching to
administrator (`POST /api/elevate`) also calls `clear_logs()` after a successful
launch, so the elevated session starts with an empty log; a cancelled UAC
prompt leaves logs untouched. Added 5 tests; focused 66 passed, full suite 371
passed, 3 skipped, coverage 83.40%, `node --check` clean. A stale untracked
`modules/__pycache__` was removed again. Confirming the crash no longer
reproduces on the user's machine is manual.

**Live-traffic disappearance follow-up (2026-11-19):** `dashboard.js` no longer
freezes the trace on a 401 (that branch used to `return` without pushing a
sample), and all request setup now lives inside the `try` so the `statusInFlight`
guard cannot leak on an early throw. The abort timeout is 4s, shorter than the
5s poll, so an abort and the next poll cannot collide into a 10s animation gap.
`updateTrafficCeiling()` drives `scales.y.max` from the current rate (grow
immediately, ease down, snap to the 1 Mbps idle range at the floor) because
Chart.js otherwise auto-scales to the largest value in the 60-sample window and
leaves the 0.05 idle line sub-pixel after a burst/disconnect. Traffic also falls
faster than it rises (`TRAFFIC_DROP_FACTOR`), visibility changes call
`chart.resize()`, and the legend cannot hide the last visible series. Added a
contract test; `node --check` clean, full suite 372 passed, 3 skipped. Visual
confirmation over a long session and a real disconnect is still manual.

**Silent-exit / native-crash follow-up (2026-11-19):** Windows Event Viewer showed repeated `APPCRASH` events for the **installed** `NetScope.exe` (exception `0xc0000005`, faulting module `python314.dll`, plus a .NET Runtime unhandled exception), i.e. a native pythonnet/WebView2 crash in the Python 3.14 build — not a Python exception or the idle monitor. The idle-shutdown path was still hardened: `web/run.py::_run_window_session()` now runs a `netscope-window-heartbeat` thread that calls `state.touch()` every 30s while the native window is open (interval via `WINDOW_HEARTBEAT_INTERVAL_SECONDS`), so a busy/backgrounded WebView2 renderer cannot let the 2s monitor `os._exit(0)` a live window. `config.WEB_IDLE_SHUTDOWN_SECONDS = _int_env("NETSCOPE_WEB_IDLE_SHUTDOWN_SECONDS", 300, minimum=30, maximum=86400)` replaces the old hard-coded 120s in `WebState.should_shutdown()`. The exe and installer were rebuilt with **Python 3.12.10** (venv) + pythonnet 3.2.1 / pywebview 6.2.1: `dist/NetScope.exe` 12.9 MB, `dist/installer/NetScope-Setup.exe` 14.7 MB, silently installed over the old copy. Full suite 373 passed, 3 skipped; coverage 83.40%; frozen smoke 2 passed; new build survived 95s with no new WER events. Many stale `msedgewebview2` processes from earlier crashes remain on the machine; a reboot (or targeted cleanup) is advisable.

**Low-request / stepped-chart follow-up (2026-11-19):** to protect low-end machines, `web/static/js/dashboard.js` now polls `/api/status` every 15s (was 5s), `/api/packet-loss` every 180s (was 60s), keeps a 40-sample window (was 60), and disables Chart.js animation/transitions so the trace steps instead of sliding. `visibilitychange` refreshes are throttled using `lastStatusRequestAt`/`lastPacketLossRequestAt`; `web/static/js/web-init.js` heartbeats every 20s (was 5s). `STATUS_ABORT_TIMEOUT_MS` is capped at 6s. `node --check` clean, full suite 373 passed, 3 skipped, coverage 83.40%. Exe/installer rebuilt and silently reinstalled (12.9 MB / 14.7 MB); frozen smoke 2 passed, installed app served the new assets, survived 90s, and produced no new WER events.

**Traffic-chart polling watchdog follow-up (2026-11-19):** added an independent
status/watchdog heartbeat that pushes the last known real receive/transmit rate
when no status sample arrives for one polling interval. This keeps rolling
labels and Chart.js data moving if a status request cycle is skipped or stalls,
without creating overlapping `/api/status` calls.

**Full process-termination follow-up (2026-11-19):** `core/processes.py` now owns
bounded, current-user-only NetScope process discovery and terminate-then-kill
cleanup; browser/WebView2 helpers are only killed as tracked descendants, never
by name, and the lock PID is verified with `is_pid_netscope()` before use so a
recycled PID is left alone. CLI exit calls `finalize_processes()`, `netscope stop`
gracefully shuts down the server then force-stops stragglers, and the hidden
`__stop_all__` entry lets the Inno uninstaller free running files before deletion.
`web/run.py` tracks spawned browser processes, serves in browser mode, and now
stops the shared server when the native window closes; `web/window.py` destroys
the window on exit. `cli/installer.py` stops running processes before uninstall
and schedules detached PowerShell cleanup when the installed exe removes itself.
Full suite: 415 passed, 3 skipped; coverage 83.24%; `node --check` clean. The
frozen exe/installer artifacts have not been rebuilt with these changes, and live
window/uninstall process cleanup needs manual validation.

**Fast connectivity status follow-up (2026-11-19):** the Connectivity card no
longer labels a still-collecting cold start as "Unavailable". `core/monitoring.py`
adds a bounded, positive-only quick ping cache
(`NETSCOPE_QUICK_PING_CACHE_SECONDS`, default 10) that pings all
`INTERNET_PING_HOSTS` concurrently while the full snapshot is collecting, so a
stable connection can show Connected in about one second. Status now prefers any
reachable configured host (matching `NET-PING`) and emits explicit
`state`/`reason` fields; `dashboard.js` renders pending probes as "Checking…"
with a gray dot, and the freshness badge says "Limited data · Retrying…" instead
of "Data unavailable" when only full details are missing. Full suite: 418 passed,
3 skipped; coverage 83.26%; `node --check` clean. Live cold-start timing on a
slow machine remains a manual validation item.

**Polling/termination gap follow-up (2026-11-19):** `dashboard.js` now uses one
`PACKET_LOSS_POLL_INTERVAL_MS = 180000` constant for both the 3-minute poll and
the `visibilitychange` throttle; the old 60-second visibility check produced an
extra packet-loss request on tab switches. `cli/stop.py::stop_running_ui()` now
force-stops remaining NetScope processes in a `finally` block, so a failed
session handshake, a rejected shutdown, or a request error cannot leave the UI
alive during `netscope stop` or uninstall (`__stop_all__`). Both fixes were done
test-first (three RED/GREEN cycles, each failure verified before implementation).
Focused tests: 48 passed; full suite: 423 passed, 2 skipped; coverage 83.26%;
`node --check` clean.

**Low-storage / crash-hardening follow-up (2026-11-20):** the reported
"less free space, more crashes" correlation is now handled with bounded,
self-cleaning local data. `core/disk_space.py` adds a fail-open
`shutil.disk_usage` probe, env-overridable threshold
(`NETSCOPE_MIN_FREE_DISK_MB`, default 250), oldest-first `prune_files()` with
count/age/byte caps and protected paths, and structured `disk_space_status` /
`disk_space_low` / `optional_write_skipped` events. Reports
(`NETSCOPE_REPORT_MAX_FILES`/`_MAX_MB`) and fix backups
(`NETSCOPE_BACKUP_MAX_FILES`/`_MAX_MB`) are pruned before each write (the newest
backup per fix is protected for rollback); the snapshot disk cache is skipped
while space is low. Log rotation dropped from 5 MB x 5 to 2 MB x 3 via
`NETSCOPE_LOG_MAX_MB`/`NETSCOPE_LOG_BACKUP_COUNT`, and CLI startup now logs disk
status too. `web/run.py` guards lock acquire/write against `OSError`, closes the
instance-lock leak when `WebState()` or any later startup step fails, returns a
clean exit code instead of raising, and keeps the window-heartbeat and monitor
threads alive through transient errors (`monitor_error`,
`window_heartbeat_failed`), without changing the `os._exit` cleanup ordering.
`web/window.py` gives WebView2 a dedicated `%LOCALAPPDATA%\NetScope\webview`
profile via pywebview's `storage_path` (introspection-guarded, opt out with
`NETSCOPE_WEBVIEW_STORAGE=0`). Added `tests/test_low_disk.py` (16 tests). Focused
web/log/fix/monitor tests: 157 passed; full suite: 439 passed, 3 skipped;
coverage 83.11%; `node --check` clean. Real low-disk and native-crash
reproduction on the user's machine remains manual validation; the PyInstaller
one-file extraction still happens before Python starts.

**Dashboard-latency / cold-start / admin-elevation follow-up (2026-11-17):**
`core/monitoring.py` still caches one shared in-memory snapshot with background
stale refresh and startup `prewarm()`; `/api/status`, device discovery, and
packet-loss sampling reuse it instead of each paying for a full
`collect_snapshot()`. It now also loads a schema-checked `{version, captured_at,
snapshot}` disk cache from `%LOCALAPPDATA%\NetScope\snapshot.json` at startup,
serves saved data immediately with `data_freshness.state = "stale"`, and returns a
non-blocking pending payload with `state = "collecting"` on a true first launch;
failed refreshes report `state = "unavailable"` and an `error`. The Connectivity
card shows a `#data-freshness` badge ("Showing saved data · Gathering fresh
data…", "Gathering data…", or "Limited data · Retrying…") until the refresh is fresh.
Elevation restores a headless elevated backend (`--no-browser` + `windowless=True`);
the original WebView window navigates to the elevated server, stays open across the
handoff, and notifies the elevated process through `POST /__elevate_shutdown__`
when it closes. Browser-fallback handoffs also notify the elevated process on
server shutdown so it does not leak. The old 5-second handoff shutdown timer is
gone, so a UAC decline or failed handoff leaves the original server and window
running. The elevated process stores its launch handoff token and accepts the
shutdown callback without mutating its own handoff state. Structured logs now include a top-level
`pid`, bounded command output, API response `duration_ms`, and window lifecycle
events. Full suite: 350 passed, 2 skipped; coverage 83.49%. Live UAC handoff,
cold-start timing on a slow machine, and the badge still need manual Windows
validation.

**Device-name follow-up (2026-11-18):** `core/device_discovery.py` now reads the
Windows NetBIOS remote-name cache (`nbtstat -c`) and DNS resolver cache
(`ipconfig /displaydns`) once per scan as bounded, best-effort IP -> name hints.
The hints are consulted after direct `nbtstat -A` but before reverse DNS, so
devices that answer neither still get a name; failures are logged and never
abort discovery. `GET /api/devices?force=1` bypasses both monitoring and
discovery caches to force a fresh scan, and the web UI's **Refresh devices**
button uses it. Device data shape and the `Unnamed device`/rename behavior are
unchanged. Focused tests: 110 passed; `node --check` clean. Full suite: 355
passed, 2 failed, 2 skipped; the two failures are environment-only (outdated
WSL/Git Bash for the build-script test and a Windows Job Object descendant-kill
test). A stale empty `modules/__pycache__` directory was removed.

**Host-name-in-device-name follow-up (2026-11-18):** Device names now also use
`ping -a <ip>` (via `CommandRunner`, bounded at `NAME_RESOLVE_TIMEOUT_SECONDS`)
as a reverse host-name source ahead of the cache hints and `nslookup`. Because
Windows' resolver chain includes DNS, NetBIOS, LLMNR and mDNS/Bonjour, this
recovers host names for phones, printers and IoT gear that answer neither a
direct `nbtstat -A` nor a DNS PTR query; `_ping_hostname()` parses the
`Pinging <name> [<ip>]` (and Linux `PING <name> (<ip>)`) banner and ignores the
fallback that echoes the bare IP. Resolution order is NetBIOS -> `ping -a` ->
local cache hint -> reverse DNS; failures stay logged and non-fatal, and the
device data shape / `Unnamed device` rename behavior are unchanged. Focused
tests: device discovery, web API, monitoring and web design 112 passed.

**Live-traffic smoothness follow-up (2026-11-18):** `web/static/js/dashboard.js`
samples `/api/status` every 5s (was 1s) and sets the Chart.js animation duration
to that same `STATUS_POLL_INTERVAL_MS` with linear easing, so the Live Network
Traffic area trace slides continuously instead of jumping and then idling. A
`statusInFlight` guard prevents slow status requests from overlapping the next
poll and cancelling the animation (the long-uptime "flow disappears" bug); an
`AbortController` timeout releases that guard if a request stalls, and a
`visibilitychange` handler redraws/refreshes immediately when a backgrounded tab
is restored. EMA smoothing is 0.28 and the rolling window is 60 samples (~5
minutes at the current cadence); a top-level `livePointPlugin` draws a soft halo
plus bright glowing tip on the newest sample of each dataset (the "heartbeat
monitor" look). `prefers-reduced-motion` disables the chart animation.
`tests/test_web_design.py::test_traffic_chart_flows_continuously` and
`test_traffic_chart_skips_overlapping_status_polls` lock the cadence/glow/concurrency
contract; `node --check` clean, focused web/API/monitoring tests 93 passed. Full
suite: 359 passed, 2 failed, 2 skipped; the two failures remain the known
environment-only WSL/Git Bash and Job Object ones. Visual review of the trace in
a browser (including high-DPI) is still open.

**Idle-traffic visibility follow-up (2026-11-18):** a disconnected internet
drops the traffic rate to zero, and a flat `y = 0` trace was drawn on the chart's
bottom axis so the graph line looked like it vanished. `dashboard.js` now plots
a small `TRAFFIC_FLOOR_MBPS = 0.05` floor with a
`TRAFFIC_MIN_CEILING_MBPS = 1` y-axis minimum so the idle line stays just above
the baseline; real rates are kept in parallel `realDownloads`/`realUploads`
arrays so tooltips and the speed cards still show the true value. A shared
`pushTrafficSample()` adds a sample on every poll — including failed/disconnected
ones — and trims all six arrays together, so the rolling trace neither freezes
nor disappears. `test_traffic_chart_stays_visible_when_disconnected` locks the
contract; `node --check` clean, focused web-design tests 19 passed. Full suite:
360 passed, 2 failed, 2 skipped (the same known environment-only WSL/Git Bash
and Job Object failures). Visual confirmation of the idle line in a browser is
still open.

**Legacy-dashboard removal:** Phases 1-6 are complete. The secured localhost
`/api/status`, `/api/devices`, and `/api/packet-loss` successful payload
contracts are characterized in `tests/test_web_api.py`. Phase 2 core monitoring
and bounded device discovery are implemented in `core/monitoring.py` and
`core/device_discovery.py`; `core/native.py` parses packet-loss summaries, and
the adapter snapshot includes permanent MAC addresses. The focused Phase 2
suite passed (32 passed). At Phase 2 closeout, the full suite reported 317
passed, 1 failed, 3 skipped; the failure was the then-existing byte-for-byte
legacy/shared stylesheet mismatch in root `static/css/style.css` and
`web/static/css/style.css`.
Phase 3 wires one runtime-owned monitoring service into both CLI and web
runtimes; the three monitoring endpoints delegate to it, and pending/errors are
explicit in API responses and the Monitoring UI. The Phase 3 test command
passed (73 passed); the full suite at Phase 3 closeout passed (325 passed,
3 skipped).
Phase 4 removed the legacy `/api/diagnostics` routes and registry-backed
Troubleshoot UI while preserving the engine-backed Troubleshoot and Repair
Library. Its web/API and design tests pass (60 passed), and both web JavaScript
files pass `node --check`. Phase 5 moved the 14,207-entry offline OUI map into
`core/oui_vendors.json`, added the `core.vendors` resource loader, and removed
root `app.py`, `templates/`, `static/`, `modules/`, and their legacy-only tests;
`web/templates/` and `web/static/` remain. Phase 5 focused tests passed
(89 passed); the full suite passed (309 passed, 3 skipped) with 83.10% coverage.
The 19.8 MB frozen executable built successfully and its smoke test passed all
11 checks, including `/api/devices` and the OUI load event. Phase 6 removed the
retired server settings, aligned setuptools package discovery and OUI package
data, and updated the supported run/build documentation while preserving the
historical Phase C changelog with an explicit removal note. Phase 6 focused
tests passed (92 passed, 3 skipped); the full suite passed (312 passed,
3 skipped) with 83.10% coverage. The clean 19.8 MB build passed its 11-check
frozen smoke, and a built wheel contains `core/oui_vendors.json`.

## Run / environment
- The standalone Flask/LAN dashboard (`app.py`) was removed in Phase 5; there
  is no legacy standalone server. Use `netscope gui` for the
  localhost interface.
- This checkout currently has no `.venv`.
  Recreate with `py -m venv .venv`, then
  `.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt`.
- Run tests: `.\.venv\Scripts\python.exe -m pytest` (latest full run: 366 passed,
  3 skipped, 2026-11-18, excluding untracked WIP `tests/test_stop.py`; Phase 5/6
  verification used system Python 3.14.7).
  Coverage gate (latest: 83.67%):
  `.\.venv\Scripts\python.exe -m pytest --cov=core --cov=fixes --cov=powershell --cov-fail-under=80`.
- Run the CLI: `.\.venv\Scripts\python.exe netscope.py --help`
  (or `python -m cli`). `netscope.py diagnose --json` is the machine interface.
- Run the web UI: `netscope gui` launches the localhost interface in a
  pywebview/WebView2 window; use `--browser` to force Edge/Chrome or
  `--no-browser --port N` to run it in the foreground and print its boot URL.
  The hidden `__gui__` entry serves the UI in-process. tkinter is gone;
  `cli/launch.py` owns console detection/detach/relaunch and `web/window.py`
  owns WebView2 detection/window hosting.
- Double-clicking `NetScope.exe` (windowed build, no args) opens the GUI
  directly: no console window, no Windows Terminal tab, no taskbar button and
  no flash. `cli.launch.attach_parent_console()` reattaches CLI output when the
  exe is run from a terminal; source runs are unaffected. `netscope` with no
  args in a shared terminal opens the shell.
- PowerShell is required for diagnostics (Windows PowerShell 5.1).
## New architecture (Phase 1)
- `core/models.py` â€” `Status`, `Layer`, `CheckResult`, `DiagnosticReport`,
  pipeline order (`LAYER_ORDER`), exit-code logic.
- `core/runner.py` â€” the **single mockable command interface**.
  `CommandRunner.run(args, timeout=...)`; `SubprocessRunner` (never `shell=True`,
  `CREATE_NO_WINDOW`, timeouts, encoding-safe capture, logs every command) and
  `FakeRunner` for tests.
- `core/native.py` â€” native ping/netsh/arp/route parsing, defensive against
  localized/malformed output.
- `powershell/scripts.py` â€” static PowerShell query fragments (`BATCH_QUERIES`);
  no user interpolation. `powershell/runner.py` â€” `PowerShellLayer` runs scripts
  from a temp `.ps1` via `-File`, passes user values as separate `-ParamName
  value` arguments, batches all queries into one PowerShell startup, parses JSON,
  detects `ConstrainedLanguage`.
- `powershell/validation.py` â€” strict validators for hosts, IPs, ports, adapter
  names, profile names, fix IDs, paths. Reject shell metacharacters/control chars.
- `core/snapshot.py` â€” collects one immutable `Snapshot` (batched PowerShell +
  needed native tools including `arp`, MTU subinterfaces and pings) that all
  checks consume.
- `core/info.py` â€” builds the plain-data `info` view (adapters, addressing,
  routes, ARP, DNS, proxy, VPN, Wi-Fi, MTU, admin status is added by the CLI).
- `core/checks/` â€” one module per layer (`adapter`, `services`, `ip`, `gateway`,
  `lan`, `dns`, `internet`, `stack`); each exposes `run(ctx) -> list[CheckResult]`.
- `core/subnets.py` â€” finds private remote LAN subnets from the routing table
  (excluding local/virtual/loopback/link-local ranges) and picks their lowest-
  metric next hop. `collect_snapshot` pings up to 8 of those next hops, and the
  `LAN-03` check reports cross-subnet LAN reachability (route present but next
  hop silent / no next hop / not tested). It is block-level only: NetScope
  probes the next-hop router, not arbitrary hosts behind it.
- `core/probes.py` â€” pure-Python socket/DNS/HTTP probes (`NetworkProbe`,
  `FakeProbe`) with timeouts.
- `core/engine.py` â€” `DiagnosticEngine.diagnose(layers=None, snapshot=None,
  progress=..., on_check=..., mode=...)`; builds the snapshot, runs layers in
  order, captures check exceptions as `ERROR` results, reports progress per
  layer and optionally per result.
- `core/logging_config.py` â€” JSON-lines rotating logs. **Do not create a
  top-level `logging/` package** (it would shadow the stdlib).
- `config.py` â€” app version, timeouts, pipeline constants, `%LOCALAPPDATA%`
  paths (`data_dir`, `log_dir`, `report_dir`, `backup_dir`).

## CLI (Phase 2)
- Entry points: root `netscope.py`, `cli/main.py`, `python -m cli`. Rendering and
  terminal concerns stay in `cli/`; diagnostics stay in `core/`.
- `cli/parser.py` â€” argparse commands: `diagnose`, `fix`, `info`, `ping`,
  `trace`, `dns`, `arp`, `routes`, `ports`, `mtu`, `monitor`, `logs`, `report`, `gui`,
  `install`, `uninstall`, `--version`. Global flags: `--json`, `--no-color`,
  `--quiet`, `--verbose`, `--yes`, `--dry-run`, `--yes-i-understand-risk`.
  Usage errors exit 64 (custom `CliArgumentParser.error`).
- `cli/commands.py` â€” dispatch/handlers. `diagnose` streams each result to stdout
  as it completes (stderr shows collection), then a summary. `--json` emits one
  document without the full snapshot. `info` uses `core/info.py`. `fix` resolves a
  finding or fix ID, shows the preview (finding, cause, exact commands,
  admin/risk/reboot, snapshot plan), confirms, runs the ladder, verifies by
  re-checking, and prints outcome + rollback/if-unresolved. Options: `--dry-run`,
  `--yes`, `--yes-i-understand-risk`, `--rollback`, `--adapter`, `--target`,
  `--value`, `--param`. Non-TTY without `--yes` errors with exit 64.
  `report` includes unresolved sections from `build_unresolved_sections()`.
- `cli/utilities.py` â€” validated `ping`, `trace`, `dns`, `arp`, `routes`,
  `ports` (port-spec expansion capped at 1024) and `mtu` (DF-ping binary search
  548-1472 payload â†’ path MTU).
- `cli/colors.py` â€” ASCII status symbols + ANSI colour; disables on non-TTY,
  `NO_COLOR`, `TERM=dumb`, `--json`/`--quiet`; enables Windows VT via ctypes.
- `cli/shell.py` â€” `netscope>` shell, history/completion when stdlib `readline`
  exists, `help`, numbered `menu`, `exit`. Shell commands reuse the same parser
  and dispatch. Type `monitor` to enter live dashboard mode.
- `cli/monitor.py` â€” ANSI-based live monitoring dashboard (`netscope monitor`).
  Periodic diagnostics (default 3s interval), real-time overall/layer/key-findings
  view, keyboard controls (`q` quit, `r` refresh, `i` interval). Requires TTY
  with color support.
- `cli/admin.py` â€” `is_admin()`, `format_admin_command()`,
  `relaunch_elevated()`; admin status is logged at startup and shown by `info`.
- `cli/exit_codes.py` â€” 0/1/2/3/4/64/130 and `--help` text.
- `logs` reads `%LOCALAPPDATA%\NetScope\logs\netscope.log`; `report` writes
  txt/json to `%LOCALAPPDATA%\NetScope\reports\` by default. `--output -` prints
  the report body to stdout.
- `SubprocessRunner` now uses `Popen` so timeouts and Ctrl+C kill the child,
  preserve timeout exit code 124, and keep stderr clean.

## Fixes (Phase 3)
- `fixes/catalog.py` â€” `CommandSpec`, `FixStep`, `Parameter`, `IfUnresolved`,
  `FixEntry`, `Catalog`; `parse_catalog()`, `load_catalog()`; validates unique
  IDs, required fields, parameter sources/validators, PS `$Param` declarations,
  native placeholders, high-risk second-confirmation, DETECT-ONLY restrictions,
  `[VERIFY]` flag on IP-08, LAN-10, DNS-04, DNS-05, NET-06, NET-08, NET-11.
- `fixes/fixes.json` â€” 62 seeded entries: ADP-01..06, SVC-01..06, IP-01..09,
  LAN-01..11, DNS-01..05, NET-01..11, VPN-01..06, WIFI-01..04, STK-01..04.
  Each has id, name, symptom, detection, explanation, admin, risk, reboot,
  snapshot (PS commands), rollback (commands + notes), verify (check IDs),
  ladder (steps with PS + native fallback), if_unresolved (this_device,
  beyond_device, next_checks, evidence_to_collect).
- `core/gateway_setup.py` â€” read-only gateway discovery for `IP-09`:
  `active_target()` picks an active physical adapter (preferring one without a
  default gateway); `detect_gateway()` ranks DHCP server/lease, existing
  gateways, default routes, then first/last/common subnet addresses, and pings
  candidates. `fixes/gateway_config.py` runs the one-click path: it skips when
  any default route exists, otherwise detects and executes `IP-09` immediately
  (snapshot/verification/rollback preserved). The web Troubleshoot header
  exposes `#auto-configure-gateway` for this action.
- `fixes/executor.py` â€” `FixExecutor`: `prepare()` builds `FixPlan` with
  resolved parameter values and preview lines; parameter sources
  `adapter_missing_gateway` and `detected_gateway` use `core/gateway_setup.py`.
  `run()` executes ladder with
  per-step confirmations (`--yes` skips normal, `--yes-i-understand-risk`
  required for risk-H), takes pre-fix snapshot, verifies by re-checking,
  stops when resolved, returns `FixOutcome` with status (resolved/dry_run/
  rolled_back/needs_admin/declined/error/detection_only/unresolved), exit code,
  step details, verification evidence, rollback availability, unresolved
  causes. `rollback()` restores latest saved snapshot for the fix ID.
- `fixes/if_unresolved.py` â€” `RankedCause`, `rank_causes()`, `unresolved_section()`,
  `build_unresolved_sections()`, `unresolved_for_results()`. Ranks
  this_device vs beyond_device using evidence + isolation answer; probabilistic
  wording ("probable"/"possible", never diagnosis); `build_unresolved_sections()`
  gated to DETECT-ONLY findings by default (fixable shown only after ladder
  exhausted via executor). Included in CLI report output.
- CLI `fix` subcommand: `netscope fix [finding|fix-id] [--dry-run] [--yes]
  [--yes-i-understand-risk] [--rollback] [--adapter NAME] [--target VALUE]
  [--value VALUE] [--param NAME=VALUE]`. Streams preview to stdout, prompts
  interactively, logs confirmations/fix_applied/unresolved. JSON output
  includes full outcome + preview on `--dry-run`.
- `tests/test_fixes.py` â€” 22 tests: catalog completeness/schema, DETECT-ONLY,
  verify flags, check fix_ids, executor resolve/dry-run/decline/admin/high-risk/
  rollback/detect-only, if_unresolved ranking/gating/wording/report, CLI
  dry-run/resolved/detect-only/unknown-id. Total 106 tests passed at Phase 3.

## Launch / runtime after tkinter removal (Phase 6 D/E)
- `gui/` is deleted. The web UI is the only graphical front end; it calls the
  same `DiagnosticEngine`, `FixExecutor`, and catalog as the CLI. Never put
  detection, fix, or validation logic in `web/` â€” extend `core/` or `fixes/`.
- `cli/launch.py` â€” `GUI_INTERNAL = "__gui__"`, `owns_console()`
  (`GetConsoleProcessList == 1`, or 2 for the frozen one-file
  bootloader parent/child pair), `attach_parent_console()` (windowed build
  reattaches to the launching terminal), `detach_console()` (tool-window style +
  `ShowWindow(SW_HIDE)` followed by `FreeConsole`, for source-console launches),
  `launch_detached_gui()` (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`,
  devnull stdio, cwd = project root), `gui_relaunch_argv()` (source:
  `[netscope.py, "__gui__"]`; frozen: `["__gui__"]`).
- `web/runtime.py` â€” `AppRuntime` (engine/catalog/runner/ps/logger/
  admin_check/session_id/backup_dir, `executor()` factory), `build_runtime()`
  (fresh `web`-mode logging + real catalog; empty catalog if it fails to load)
  and `runtime_from_context()` (reuse a `CliContext`). Moved from
  `gui/runtime.py`; renamed from `GuiRuntime`.
- `cli/main.py` intercepts `__gui__` before argparse and runs the web server in
  process (`_run_gui_process`). No arguments + owned console routes to GUI
  before argparse setup; `netscope gui` (`cmd_gui`) spawns the detached
  server and returns 0. No args + own console â†’ detach + GUI; no args in a
  shared terminal â†’ shell; no args without a TTY â†’ help/exit 64.
- `web/run.py` owns the single-instance lock, port file, `/health` reuse,
  bounded boot URL, bind-failure logging, heartbeat/idle shutdown, and clean
  `POST /api/shutdown`.
- Launcher tradeoff: the exe is windowed, so a double-click shows no console at
  all; CLI output is restored with `AttachConsole(ATTACH_PARENT_PROCESS)` when
  launched from a terminal. A double-clicked `.py` via `py.exe` shares a console, so
  `owns_console()` is False and it opens the shell â€” the frozen exe behaves as
  specified.
- `tests/test_launch.py` covers the retained launch helpers. `tests/test_gui.py`
  was deleted with the tkinter front end.

## Desktop window and installer (Phase 7)
- `web/window.py` â€” `WEBVIEW2_CLIENT_ID`, `_webview2_version()` (HKCU/HKLM/
  WOW6432Node EdgeUpdate `pv`), `webview2_available()` (requires a non-zero
  four-part version), and `run_native_window(boot_url)` (pywebview
  `edgechromium`, centered in the primary work area, max 1280x860 with
  24-pixel margins, minimum clamped from 900x600, blocks until close). Failures
  return `False`; `web/run.py` logs `webview_unavailable` and falls back to the
  browser.
- `web/run.py` launch modes: `window` (default), `browser`, `no_browser`.
  `_acquire_lock_with_wait()` waits up to 10s for a new owner after `--replace`;
  `_show_existing()` verifies `/health` and reopens the shared server;
  `_run_window_session()` owns the pywebview window lifecycle. Closing the
  window, `netscope stop`, `POST /api/shutdown`, Ctrl+C, or the heartbeat timeout
  stops the shared server and its owned processes.
- CLI: `netscope gui [--browser] [--no-browser] [--port N]`; hidden
  `--print-url` for the detached child and `--replace` for the elevated
  handoff. `cmd_gui` detached child runs `__gui__ --print-url`; when run in a
  TTY, `netscope gui` opens the window in a detached process and returns.
  `web/api.py` `/api/elevate` calls `gui_relaunch_argv(replace=True)`; declining
  UAC logs `elevate_cancelled`, returns 409, and leaves the old server running.
- `cli/installer.py` portable install uses `.netscope-install`;
  `INNO_MARKER_NAME = ".netscope-inno"`. `_reject_inno_managed()` makes both
  `install()` and `uninstall()` raise `InstallerError` directing users to
  **Settings > Apps** for installer-managed copies.
- `installer/NetScope.iss` â€” per-user Inno Setup 6/7; AppId
  `{8E6F1C2A-4B7D-4E3A-9C5F-2D1B7A6E8F04}`, install
  `{localappdata}\Programs\NetScope`, `PrivilegesRequired=lowest`, PATH/App
  Paths, Start Menu + optional desktop shortcut, `.netscope-inno`, WebView2
  bootstrap/offline handling. Uninstall removes app/PATH/App Paths/shortcut and
  prompts to delete `{localappdata}\NetScope` (Yes is default); silent
  uninstalls skip the prompt and use Yes.
- `scripts/build_installer.ps1` reads `config.APP_VERSION` or `-Version`, finds
  `ISCC.exe` (PATH, per-user Programs, Program Files 6/7), and writes
  `dist/installer/NetScope-Setup.exe`.
- `scripts/installer_smoke.py` installs silently, checks shortcut/App
  Paths/PATH/`--version`, creates a user-data marker, uninstalls silently, and
  waits for app/shortcut/registry/data removal. It is destructive by design:
  run it in a disposable profile or back up `%LOCALAPPDATA%\NetScope` first.
- `NetScope.spec` adds `collect_all("webview")`, `collect_all("pythonnet")`,
  `collect_all("clr_loader")`, `web.window`, and the platform/clr hidden imports;
  excludes the Android webview platform. Current exe: 19.8 MB; setup: 21.6 MB.
- `.github/workflows/ci.yml` has an `installer` job after `build`: downloads the
  exe artifact, installs Inno via Chocolatey if needed, builds the setup, runs
  the silent smoke, and uploads `NetScope-Setup`.

Usage:
```python
from core.engine import DiagnosticEngine
report = DiagnosticEngine().diagnose(layers=["adapter", "ip"])
print(report.exit_code, report.first_failing_layer, report.to_dict())
```

```python
from fixes.catalog import load_catalog
from fixes.executor import FixExecutor
from core.engine import DiagnosticEngine

catalog = load_catalog()
engine = DiagnosticEngine()
snapshot = engine.collect_snapshot()
report = engine.diagnose(snapshot=snapshot)
entry = catalog.require("IP-01")
executor = FixExecutor(runner, ps, logger, engine, catalog)
plan = executor.prepare(entry, snapshot=snapshot)
outcome = executor.run(entry, plan=plan, assume_yes=True)
print(outcome.exit_code, outcome.status, outcome.to_dict())
```

```python
from web.runtime import AppRuntime, build_runtime

runtime = build_runtime()  # same engine/catalog as the CLI, web-mode logging
```

## Web UI (Phase 6 complete)
- `web/run.py` serves on `127.0.0.1`, owns a per-user process lock, atomically
  publishes its port/boot token, validates existing instances with `/health`,
  and uses a bounded detached-launch URL handoff. Source startup is banner-free.
  The server binds via `werkzeug.serving.make_server` *before* advertising the
  boot URL/port lock; werkzeug 3.x turns bind errors into
  `print(strerror)` + `sys.exit(1)` inside `BaseWSGIServer.__init__`, so
  `run_web_ui` catches both `SystemExit(1)` and `OSError`, logs
  `server_bind_failed`, and returns 1 cleanly (verified against the real
  stack, 2026-11-11). A monitor thread handles explicit shutdown (sleeps briefly
  to flush the HTTP response, logs `server_shutdown`, removes the port lock,
  `os._exit(0)`),   while heartbeat timeout shutdown is gated on
  `jobs.has_active_jobs()`; the heartbeat threshold is 120s to survive
  Chrome's background-tab timer throttling.
- `web/security.py` enforces localhost Host checks, boot/session tokens,
  same-origin state-changing requests, CSP, and security headers.
- `web/server.py` builds the runtime explicitly with `SubprocessRunner`,
  `PowerShellLayer` and `NetworkProbe` (so `/api/status` reports a live
  PowerShell layer) and falls back to `empty_catalog()` with a logged
  `fix_catalog_unavailable` warning if the catalog fails to load.
- `web/jobs.py` provides SSE plus job polling, cancellation states, and a
  job-scoped command cancellation context. Windows commands use kill-on-close
  Job Objects so cancelled commands and descendants terminate together.
  Streams mark `Job.events_done` under the job lock and drain with `get_nowait`
  first, so a stream opened on a finished job ends immediately (0.0s instead of
  the old 15s timeout) and keep-alives are sent only while genuinely idle.
  `JobManager.has_active_jobs()` is the single source for idle-shutdown gating.
- `web/api.py` routes operations through the existing engine, catalog,
  `FixExecutor`, `UtilityRunner`, report builder, and structured logger. Do not
  add diagnostic or fix business logic to the web layer. `/api/logs/stream`
  emits keep-alives when idle and stops on `shutdown_event`; fix execution does
  not pass the stale `snapshot=` kwarg to `FixExecutor.run()`. The Troubleshoot
  network tools include a user-confirmed speed test against
  `speed.cloudflare.com` (10 MiB download, 2 MiB upload).
- The overview card is a combined Connectivity card showing both Internet and
  Gateway status (`#internet-dot`/`#gateway-dot`), fed by `/api/status`
  `internet_ping` and `gateway_ping`.
- `web/static/js/engine-ui.js` directly wires the shared Troubleshoot controls
  to the template nodes; the legacy clone-and-replace and `MutationObserver`
  workarounds are removed. `web/static/js/dashboard.js` retains Monitoring
  behavior but no registry-backed Troubleshoot renderer or handlers. The
  `#auto-configure-gateway` control still calls `/api/gateway/configure`.
- The Repair Library (`data-view="repairs"`, nav below Troubleshoot) lists every
  catalog entry as a row (id/name/symptom/risk/admin) and renders its procedure
  from `/api/fixes/<id>`: plain-language steps, collapsible exact commands,
  verification, rollback, and if-unresolved guidance. The Troubleshoot repair
  detail links to it with **View full procedure**. A sidebar **Run as
  administrator** button calls `/api/elevate`; cancellation (UAC declined) logs
  `elevate_cancelled`, returns 409 and keeps the server running.
- Tests: latest full suite is 280 passed, 2 skipped (2026-11-16). Session 30's
  live repro verified the real CLI child, boot/session/CSP, local assets, 33 SSE
  check events, findings/fixes/catalog, fix plan+dry-run, log streaming,
  shutdown, single-instance reuse and bind-failure logging (25/25); the gateway
  repair adds `/api/gateway/configure` and combined Internet/Gateway status.
  `scripts/browser_smoke.py` now drives the real UI in headless Playwright
  Chromium: shell/session/CSS, stat-card layout, mobile drawer, Troubleshoot,
  shutdown, plus dashboard/mobile/Troubleshoot screenshots. Frozen-build
  launch/log checks live in `scripts/frozen_smoke.py` + `tests/test_frozen.py`.
- UI overhaul (Session 41, Phase C design pass): `web/templates/base.html` +
  `web/templates/index.html` restructured (skip-link, mobile topbar +
  `#nav-toggle`/`aside.sidebar`/`#sidebar-backdrop` drawer, SVG nav icons,
  conn-grid Connectivity card, `.btn`/`.btn-secondary`/ghost buttons carry an
  SVG + `<span class="btn-label">` so busy state text swaps via
  `setButtonLabel`/`.btn-label`, `.top-status[data-live]` live badge,
  footer shows `config.APP_VERSION` + `#footer-time`). Stat cards: the
  Connectivity card is a full-width hero row (`grid-column: 1 / -1`) with the
  four single-metric cards in an even 4-up row below (the old 6-track
  single-row grid squeezed them to ~141px and wrapped their labels; verified
  via headless-Edge DOM measurement, cards now 219px at the same width; pairs
  up below 1180px as before). `style.css` is the full
  shared design system; `web-overrides.css` holds engine-view components
  (layer controls, evidence, `.engine-output` cards + `.engine-copy`, fix-fact
  chips, dialogs, tool panel, admin control, Repair Library with
  `.repair-search` filtering + `.repair-search-count`). `engine-ui.js` gained
  `svgIcon`/`emptyState`/`fixFact`/`renderFixFacts`/`setButtonLabel` helpers,
  empty states, and label-aware busy buttons. `dashboard.js` (web) renders
  adapter pills (`adapter-dot`/`adapter-body`/`adapter-state`), sets
  `data-live` (success/catch/401), uses `\u2715` error markers, null-guards
  `#repair-steps` (web template has none â€” repairs live in the Repair Library)
  and disables the Refresh devices button via `setRefreshDevicesBusy`. Brand:
  NetScope carries as a solid-colour wordmark (no gradients) in the sidebar and
  mobile topbar. The Wi-Fi signal glyph is the favicon and the
  `assets/netscope.ico` exe/installer icon (`NetScope.spec`,
  `installer/NetScope.iss`). Phase C also synced the then-existing standalone
  dashboard to this design; Phase 5 removed that frontend and its root assets.
  Test constraints drove markup:
  the web templates must keep the literal tags `<aside class="sidebar">`,
  `<main class="main">`, `<footer>` (no extra attributes on those tags â€” the
  skip link targets the inner `#main-content` wrapper div instead).
- Phase C session 42: reusable shell partials `web/templates/_page_header.html`,
  `_status.html`, `_toast.html` (`#toast-region`, `window.NetScope.toast`,
  textContent-only); fix outcomes render structured steps/timings/verification
  and unresolved sections render ranked causes + next checks + evidence;
  Network info renders tables with copy/export/refresh; utilities export and use
  the shared cancel control. `docs/phaseC-web-ui.md` is the design-file
  changelog/offline-CSP audit/parity map. `tests/test_web_design.py` enforces
  offline/local assets, no inline handlers/scripts/styles, no unsafe DOM sinks,
  design tokens/breakpoints, shared-CSS identity, and changelog coverage;
  autoescape tests live in `tests/test_web_api.py`. Browser E2E/design
  screenshots remain open (no browser on this host).
- Phase C session 42b: `FixExecutor.run(progress=...)` emits best-effort
  snapshot/step/verify/guidance events (swallows callback errors);
  `/api/fix/execute` forwards them as `fix_progress` job events, and the web
  Troubleshoot stage renders an APPLYING FIX progress bar with per-step
  running/verifying/done chips before the structured outcome. Fix History and
  Recent Logs render readable rows (localized time, badges, compact field
  summaries) instead of raw JSON; rollback appears only on the newest snapshot
  per fix, older snapshots are labelled. Tests cover executor progress events,
  callback-failure safety, and web forwarding; full suite 229 passed.

## Logging
- JSON-lines file at `%LOCALAPPDATA%\NetScope\logs\netscope.log`, rotating
  (5 MB Ã— 5). Every record has `ts`, `level`, `logger`, `session_id`, `event`,
  optional `fields`; secrets are redacted.
- Structured logger helpers: `event`, `debug`, `warning`, `error`, `command`,
  `check`, `confirmation`, `fix_applied`, `unresolved`, `action`.
- `setup_logging(mode, session_id, log_dir=..., console=...)` reinitialises
  handlers safely.

## Check results / exit codes
- Each result carries `id`, `layer`, `status` (pass/warn/fail/skip/error),
  message, `cause`, `evidence`, `fix_ids`, `detection_only`.
- `report.exit_code`: 0 all pass/skip, 1 warnings, 2 fail/error. CLI adds 3 fix
  failed, 4 needs admin, 64 usage error, 130 Ctrl+C.
- Check IDs use descriptive IDs (e.g. `GW-02`, `NET-PING`) while `fix_ids`
  reference the future catalog (`ADP-01`, `IP-01`, `LAN-02`, ...).

## Phase 1 behaviour that was validated on the real machine
- Full pipeline works end-to-end against real `Get-NetAdapter`/`Get-NetIP*`,
  netsh, arp, ping, DNS and HTTP. `collect_snapshot` returns all major sections.
- APIPA/stale-lease/IP-overlap checks intentionally ignore virtual, disconnected,
  Bluetooth, Wi-Fi Direct, Npcap loopback and `Local Area Connection*` adapters.
- PnP driver errors only count for real NICs and critical problem codes
  (10/28/31/43); Bluetooth/WAN Miniport/Kernel Debug/Wi-Fi Direct are ignored.
- Winsock third-party detection only considers `Layered Service Provider` entries,
  so Microsoft base providers (MSAFD, Hyper-V RAW, AF_UNIX, ...) do not warn.
- Firewall discovery check evaluates a group as enabled if any inbound Allow rule
  is enabled (avoids false "62 rules disabled").

## Historical legacy dashboard notes (removed in Phase 5)
The following describes pre-Phase 5 behavior for historical context only; it is
not current functionality.

- `app.py` exposes `/`, `/api/status`, `/api/devices`, `/api/diagnostics`, and
  `POST /api/diagnostics/<step_id>/run`; `static/js/dashboard.js`
  polls `/api/status` every 2000 ms (`config.REFRESH_INTERVAL_MS` is unused; only
  `PING_TIMEOUT_SECONDS` is read). No authentication: the dashboard and the
  diagnostics/repair endpoints are reachable by anyone who can access port 5000.
- `modules/diagnostics.py` is a registry of predefined checks/repairs (adapter
  status, IP config, loopback, gateway/internet ping, DNS, traceroute, DNS
  flush, DHCP renew, Winsock/TCP-IP reset). Commands are argv lists â€” never
  shell strings â€” and the client can only select a known `step_id`; there is
  no arbitrary command execution. Windows-only repairs report as unsupported
  elsewhere. `run_diagnostic` returns `{id, success, commands, output,
  duration_ms}`; `list_diagnostics` returns each step's `id`, `title`,
  `description`, `kind`, `requires_admin`, `supported`, `available`,
  `command`, `reason`, `timeout`, plus `elevated`, `system`, `check_count`,
  `repair_count`.
- `BandwidthMonitor` is a module-level singleton; rates are deltas between
  requests (multiple tabs or a changed poll interval distort readings); the
  dashboard applies EMA smoothing (`SMOOTHING_FACTOR = 0.34`) client-side.
- Each `/api/status` call synchronously shells out to `ping` twice
  (hardcoded internet host `1.1.1.1` and the detected gateway); ping output
  is regex-parsed per OS. `modules/network_info.get_default_gateway()` uses
  `_windows_default_gateway()` to handle `ipconfig` output where an IPv6
  gateway line is followed by the IPv4 gateway on a continuation line.
- Device discovery uses UDP ARP-cache warming plus concurrent pings to local
  private-subnet hosts (max 1024 targets, 64 workers, 15 s cache) before
  parsing `arp -a`; UDP remains effective for devices that ignore ICMP. It
  filters multicast/broadcast entries and never scans public/routed networks.
  Names via NetBIOS UDP 137 then reverse DNS (1.5 s budget, 300 s/60 s caches).
  The dashboard retries `/api/devices` after 6 s.
- Brands come from the offline OUI map in `modules/oui_vendors.py`
  (common-prefix subset generated from Wireshark's `manuf` data at
  `https://www.wireshark.org/download/automated/data/manuf`); locally
  administered MACs show `Private MAC`. Regenerate this data if vendor
  coverage is insufficient. The device table has six columns (name, brand,
  IP, MAC, connection, entry type); `/api/devices` returns `name`, `vendor`,
  `ip`, `mac`, `connection`, `connection_detail`, `type`. `connection` is a
  best-effort label (`This PC`, `Router`, `Wireless`, `Wired`, `Unknown`)
  derived from ARP interface mapping (Wi-Fi adapter names), the default
  gateway (with `route print -4` fallback), randomized MACs, and
  mobile/IoT vendor OUIs â€” Windows does not expose the AP's client list.
  Each entry also carries `mac_randomized`, `hardware_mac` and `mac_note`.
  Remote devices with randomized (locally administered) MACs are flagged
  because their real hardware MAC is hidden by design; the PC's own active
  adapters are added as `type: "local"` rows with their real hardware MAC
  (queried from `Get-NetAdapter` `PermanentAddress`, with virtual adapters
  and locally administered/unknown permanent addresses excluded).
  Device overrides are in browser localStorage; double-click a name
  to rename it. The table shows up to 8 rows (`DEVICE_VISIBLE_ROWS` in
  `dashboard.js`; `applyDeviceScrollHeight()` measures the sticky `thead`
  plus the first 8 rows and sets `.table-wrap` max-height, rerun on device
  refresh and window resize; 420px CSS fallback). `#device-count` is a pill
  updated on each `/api/devices` render.
- Chart.js and Inter fonts are bundled locally in `static/` and `web/static/`;
  the dashboard no longer depends on a font or chart CDN. `dashboard.js` still
  initializes Chart.js at startup, so the referenced local asset must remain
  present (covered by the web template asset test).
- The Troubleshoot panel is a master-detail UI: `#check-steps`/`#repair-steps`
  render a grouped rail and `#diag-stage` renders the selected step.
  Per-step results live in `diagnosticStates`;
  `updateDiagnosticsSummary()` drives the progress bar
  (`#diag-progress-fill`, `#troubleshoot-percent`). Unsupported steps stay
  selectable so their `reason` is visible, but their run button is disabled.
  Repairs prompt via `window.confirm` and warn when not elevated.
- `database/db.py` is not imported anywhere â€” the SQLite schema is unused
  scaffolding (`database/netscope.db` is gitignored).
- Phase 5 removed the standalone server, root `templates/` and `static/`
  assets, and the old `modules/` package. The supported web UI remains under
  `web/`, uses the shared core monitoring services, and binds only to localhost.

## Safety invariants (do not break)
- All system calls go through `CommandRunner.run`; never `shell=True`, never
  `os.system`, never build shell strings from user input.
- PowerShell scripts are static catalog text; user values are separate argv.
- Validate all user input before it reaches a command (`powershell/validation.py`).
- Timeouts on every command; record state before changing it (fix phases).
- Never enable SMB1, disable SMB signing, or disable NCSI active probing by
  default (DETECT-ONLY or second confirmation only).

## Packaging / installer / CI (Phase 5, Phase 6 D/E, Phase 7)
- `NetScope.spec` is a one-file windowed-subsystem PyInstaller build (UPX off)
  bundling `web/templates`, `web/static`, `fixes/fixes.json`,
  `core/oui_vendors.json`, pywebview, pythonnet, and clr_loader; tkinter and
  heavy optional libs are excluded. `scripts/build.ps1` uses the venv
  interpreter when available (`-Clean` wipes `build/` + `dist/`) and reports
  the exe size. Current artifact: 19.8 MB.
- `scripts/frozen_smoke.py` runs the frozen exe with an isolated
  `LOCALAPPDATA`: boot URL, localhost UI, bundled CSS, `/api/status`,
  `/api/devices`, bundled OUI resource, quiet console, structured `source:web`
  logging, shutdown, clean exit, and port-lock removal (11 checks).
  `tests/test_frozen.py` wraps it plus `--version` and is skipped unless
  `NETSCOPE_EXE` is set.
- `cli/installer.py` implements per-user `netscope install`/`uninstall`:
  PATH (user), App Paths, Start Menu shortcut, marker file; supports
  `--dry-run`, `--json`, `--purge`. It never needs admin and never touches
  machine-wide keys.
- `.github/workflows/ci.yml` (windows-latest, triggered only by pushes/merges to
  `main`; no PR or feature-branch runs): `test` matrix on Python 3.11 and
  3.14 with coverage over `core`/`fixes`/`powershell` (`--cov-fail-under=80`),
  a `browser` job installing Playwright Chromium and uploading
  `artifacts/browser-smoke` screenshots, a `build` job that runs the
  PyInstaller build, frozen smoke + frozen pytest, and uploads
  `NetScope-windows-x64`, and an `installer` job that downloads the exe,
  installs Inno via Chocolatey if needed, builds and silently smoke-tests
  `NetScope-Setup.exe`, and uploads `NetScope-Setup`.
- Docs: `README.md` (install/build/CLI/API/extension guide),
  `docs/manual-test-checklist.md` (Windows 10 VM checklist),
  `docs/known-unverified.md` (`[VERIFY]` repairs + Win10/Win11 caveats),
  `docs/phaseDE-report.md` (packaging/lifecycle/CI report),
  `docs/phaseE-deliverables.md` (close-out index).
- CI has not been run remotely (nothing pushed). A real Windows 10 VM run and
  human review of the browser screenshots remain open.

## Remaining work
- Run `docs/manual-test-checklist.md` on a real Windows 10 VM, including the
  `[VERIFY]` repairs (`IP-08`, `LAN-10`, `DNS-04`, `DNS-05`, `NET-06`, `NET-08`,
  `NET-11`), the WebView2 window/browser fallback, UAC replace handoff, and the
  Inno install/uninstall/data-prompt cases.
- Review the Playwright screenshots visually and on a high-DPI display.
- Rebuild the frozen exe/installer with the process-termination changes, then
  verify window close, `netscope stop`, and running-app uninstall leave no
  NetScope processes behind.
- Keep `LAN-09` DETECT-ONLY (deliberate deviation from `prompt.txt`) and keep
  the console-flash launcher tradeoff documented.
## Dev install / running
- `pip install -e .` (after requirements) exposes the `netscope` command from any
  shell. Run `netscope --help`, `netscope diagnose`, `netscope gui`.
- Troubleshoot now lists all 32 planned checks before a run (via
  `/api/checks` + `core/checks/descriptors.py`); repairs live only in the
  Repair Library. The diagnostic rail scrolls independently of the detail pane.
- The web Troubleshoot tab shows per-layer status from streamed diagnostic check
  results; layers are marked Not run until diagnosed and show in-progress and
  aggregated pass/warn/fail/error/skip states during and after a run.
## Packaging layout
- `pyproject.toml` exposes `config.py` as a top-level module, discovers the
  `cli`, `core`, `fixes`, `powershell`, and `web` packages, and includes
  `core/oui_vendors.json` as package data. The retired `modules` package is not
  part of the installed project.
- Verify an editable install with `netscope --help`, `netscope diagnose`, and
  `netscope gui` from outside the repository.
## Stale-UI fix (Session 37)
- `refreshDevices` referenced an undefined `devices` variable, so the device
  table never updated (stuck on "Loading..."). refreshStatus could throw on
  missing fields (latency_ms strict-null check). Both fixed with null-safe
  guards and explicit 401 handling. All /api/* endpoints verified to return
  real data with a valid session cookie.
## Initial-load / nav fix (Session 38)
- `$("repair-steps").addEventListener(...)` threw (element removed from
  template), aborting dashboard.js before refreshStatus/refreshDevices/nav
  listeners ran. Guarded all top-level addEventListener calls with null checks.
