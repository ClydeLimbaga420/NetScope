# AGENTS.md

NetScope is being evolved (per `prompt.txt`, tracked in `task.md`) from a Flask
dashboard into a universal Windows network troubleshooting tool with one shared
engine and two front ends (CLI + GUI). Work phase by phase; update this file and
`task.md` Notes at the end of every phase.

**Current status: Phase 2 complete.** Phases 3-5 are not built yet.

## Run / environment
- The Flask dashboard still works unchanged: `python app.py` → http://127.0.0.1:5000
  (binds localhost, `debug=False`, `threaded=True`).
- This checkout originally had **no `.venv`**. A venv now exists (Python 3.14.7).
  Recreate with `py -m venv .venv`, then
  `.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt`.
- Run tests: `.\.venv\Scripts\python.exe -m pytest` (pytest 9.x, 84 tests green).
- Run the CLI: `.\.venv\Scripts\python.exe netscope.py --help`
  (or `python -m cli`). `netscope.py diagnose --json` is the machine interface.
- PowerShell is required for diagnostics (Windows PowerShell 5.1).
- Run `app.py` as a script: imports are flat/absolute (`from config ...`,
  `from modules...`, `from core...`), not a package.

## New architecture (Phase 1)
- `core/models.py` — `Status`, `Layer`, `CheckResult`, `DiagnosticReport`,
  pipeline order (`LAYER_ORDER`), exit-code logic.
- `core/runner.py` — the **single mockable command interface**.
  `CommandRunner.run(args, timeout=...)`; `SubprocessRunner` (never `shell=True`,
  `CREATE_NO_WINDOW`, timeouts, encoding-safe capture, logs every command) and
  `FakeRunner` for tests.
- `core/native.py` — native ping/netsh/arp/route parsing, defensive against
  localized/malformed output.
- `powershell/scripts.py` — static PowerShell query fragments (`BATCH_QUERIES`);
  no user interpolation. `powershell/runner.py` — `PowerShellLayer` runs scripts
  from a temp `.ps1` via `-File`, passes user values as separate `-ParamName
  value` arguments, batches all queries into one PowerShell startup, parses JSON,
  detects `ConstrainedLanguage`.
- `powershell/validation.py` — strict validators for hosts, IPs, ports, adapter
  names, profile names, fix IDs, paths. Reject shell metacharacters/control chars.
- `core/snapshot.py` — collects one immutable `Snapshot` (batched PowerShell +
  needed native tools including `arp`, MTU subinterfaces and pings) that all
  checks consume.
- `core/info.py` — builds the plain-data `info` view (adapters, addressing,
  routes, ARP, DNS, proxy, VPN, Wi-Fi, MTU, admin status is added by the CLI).
- `core/checks/` — one module per layer (`adapter`, `services`, `ip`, `gateway`,
  `lan`, `dns`, `internet`, `stack`); each exposes `run(ctx) -> list[CheckResult]`.
- `core/probes.py` — pure-Python socket/DNS/HTTP probes (`NetworkProbe`,
  `FakeProbe`) with timeouts.
- `core/engine.py` — `DiagnosticEngine.diagnose(layers=None, snapshot=None,
  progress=..., on_check=..., mode=...)`; builds the snapshot, runs layers in
  order, captures check exceptions as `ERROR` results, reports progress per
  layer and optionally per result.
- `core/logging_config.py` — JSON-lines rotating logs. **Do not create a
  top-level `logging/` package** (it would shadow the stdlib).
- `config.py` — app version, timeouts, pipeline constants, `%LOCALAPPDATA%`
  paths (`data_dir`, `log_dir`, `report_dir`, `backup_dir`).

## CLI (Phase 2)
- Entry points: root `netscope.py`, `cli/main.py`, `python -m cli`. Rendering and
  terminal concerns stay in `cli/`; diagnostics stay in `core/`.
- `cli/parser.py` — argparse commands: `diagnose`, `fix`, `info`, `ping`,
  `trace`, `dns`, `arp`, `routes`, `ports`, `mtu`, `logs`, `report`, `gui`,
  `install`, `uninstall`, `--version`. Global flags: `--json`, `--no-color`,
  `--quiet`, `--verbose`, `--yes`, `--dry-run`, `--yes-i-understand-risk`.
  Usage errors exit 64 (custom `CliArgumentParser.error`).
- `cli/commands.py` — dispatch/handlers. `diagnose` streams each result to stdout
  as it completes (stderr shows collection), then a summary. `--json` emits one
  document without the full snapshot. `info` uses `core/info.py`.
- `cli/utilities.py` — validated `ping`, `trace`, `dns`, `arp`, `routes`,
  `ports` (port-spec expansion capped at 1024) and `mtu` (DF-ping binary search
  548-1472 payload → path MTU).
- `cli/colors.py` — ASCII status symbols + ANSI colour; disables on non-TTY,
  `NO_COLOR`, `TERM=dumb`, `--json`/`--quiet`; enables Windows VT via ctypes.
- `cli/shell.py` — `netscope>` shell, history/completion when stdlib `readline`
  exists, `help`, numbered `menu`, `exit`. Shell commands reuse the same parser
  and dispatch.
- `cli/admin.py` — `is_admin()`, `format_admin_command()`,
  `relaunch_elevated()`; admin status is logged at startup and shown by `info`.
- `cli/exit_codes.py` — 0/1/2/3/4/64/130 and `--help` text.
- Honest stubs for now: `fix` validates the ID, prints admin guidance, and exits
  3 until Phase 3; `gui`/`install`/`uninstall` print phase messages and exit 3.
- `logs` reads `%LOCALAPPDATA%\NetScope\logs\netscope.log`; `report` writes
  txt/json to `%LOCALAPPDATA%\NetScope\reports\` by default. `--output -` prints
  the report body to stdout.
- `SubprocessRunner` now uses `Popen` so timeouts and Ctrl+C kill the child,
  preserve timeout exit code 124, and keep stderr clean.

Usage:
```python
from core.engine import DiagnosticEngine
report = DiagnosticEngine().diagnose(layers=["adapter", "ip"])
print(report.exit_code, report.first_failing_layer, report.to_dict())
```

## Logging
- JSON-lines file at `%LOCALAPPDATA%\NetScope\logs\netscope.log`, rotating
  (5 MB × 5). Every record has `ts`, `level`, `logger`, `session_id`, `event`,
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

## Legacy dashboard notes (still true)
- `app.py` exposes only `/`, `/api/status`, `/api/devices`; `static/js/dashboard.js`
  polls `/api/status` every 2000 ms (`config.REFRESH_INTERVAL_MS` is unused; only
  `PING_TIMEOUT_SECONDS` is read).
- `BandwidthMonitor` is a module-level singleton; rates are deltas between
  requests; the dashboard applies EMA smoothing client-side.
- Device discovery warms the ARP cache (private subnets, max 1024 hosts, 15 s
  cache) then parses `arp -a`; names via NetBIOS UDP 137 then reverse DNS
  (1.5 s budget, 300 s/60 s caches). The dashboard retries `/api/devices` after 6 s.
- Brands come from `modules/oui_vendors.py`; locally administered MACs show
  `Private MAC`. Device overrides are in browser localStorage.
- Chart.js loads from a CDN (charts need internet).
- `modules/diagnostics.py` is empty and `database/db.py` is unused scaffolding.
- Do not delete `modules/`, `templates/`, `static/`, SQLite scaffolding until a
  later phase explicitly replaces them.

## Safety invariants (do not break)
- All system calls go through `CommandRunner.run`; never `shell=True`, never
  `os.system`, never build shell strings from user input.
- PowerShell scripts are static catalog text; user values are separate argv.
- Validate all user input before it reaches a command (`powershell/validation.py`).
- Timeouts on every command; record state before changing it (fix phases).
- Never enable SMB1, disable SMB signing, or disable NCSI active probing by
  default (DETECT-ONLY or second confirmation only).

## Next phases
- Phase 3: `fixes/fixes.json` catalog, executor, snapshot/rollback,
  if_unresolved engine, catalog/flow tests. Replace the `fix` stub and use
  `cli/admin.py` guidance/relaunch.
- Phase 4: tkinter GUI, dual-mode console/GUI launch, GUI smoke tests.
  Replace the `gui` stub.
- Phase 5: PyInstaller exe, installer/uninstaller (PATH/App Paths/Start Menu),
  GitHub Actions, README/manual test checklist. Replace `install`/`uninstall`.
