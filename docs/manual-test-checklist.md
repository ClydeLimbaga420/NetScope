# Manual test checklist (Windows VM)

Use these scenarios to exercise the parts that unit tests cannot prove. Run a
disposable Windows 10 or Windows 11 VM with a virtual NIC you can disconnect,
and keep a snapshot so you can roll back after repairs. Run commands from an
administrator terminal only where the scenario says so.

Record the build under test (`NetScope.exe --version`), Windows version, whether
the VM is wired/Wi-Fi, and the results for each row.

## 0. Baseline and packaging

- [ ] `NetScope.exe --version` prints the expected version.
- [ ] `NetScope.exe --help` lists every command and the exit codes.
- [ ] `NetScope.exe diagnose --json` emits one valid JSON document; the exit
      code matches the overall status.
- [ ] `NetScope.exe info`, `ping 1.1.1.1`, `dns example.com`, `arp`, `routes`,
      `ports 1.1.1.1 443`, and `mtu 1.1.1.1` all return sensible output.
- [ ] `python scripts\frozen_smoke.py --exe dist\NetScope.exe` passes.
- [ ] `NETSCOPE_EXE=dist\NetScope.exe pytest tests\test_frozen.py` passes.
- [ ] Start the exe with an isolated `LOCALAPPDATA`; confirm the
      `%LOCALAPPDATA%\NetScope\logs\netscope.log` file contains structured
      `source:"web"` request/action events and no console banner.
- [ ] Kill the server with Task Manager, then relaunch; confirm it starts (the
      stale lock/port file is ignored).

## 1. Launch and single instance

- [ ] Double-click `NetScope.exe` with a normal desktop session: no permanent
      console window, the WebView2 app window opens, and the dashboard loads.
- [ ] Win+R `NetScope`, Start Menu, and desktop shortcuts behave the same way
      (desktop shortcut only if selected during install).
- [ ] `netscope gui` from a terminal returns the prompt after opening the app
      window.
- [ ] `netscope gui --browser` opens Edge/Chrome instead of the app window.
- [ ] Temporarily rename the WebView2 runtime or force pywebview to fail; the
      app logs `webview_unavailable` and opens the browser UI.
- [ ] `netscope gui --no-browser --port 8765` prints a `/__boot__` URL and
      serves the UI at `http://127.0.0.1:8765/`.
- [ ] Close the app window; the shared server keeps running for a second
      window. Quit from the UI to stop it.
- [ ] Launch a second instance while the first is running: it reuses the
      existing UI and exits 0; there is only one server process.
- [ ] `netscope` with no arguments in a terminal opens the `netscope>` shell.
- [ ] Close all browser tabs and wait; the UI shuts down after the heartbeat
      timeout (120 s) with no active job.
- [ ] Start a long diagnosis and remove the heartbeat; the server stays alive
      while the job runs, then shuts down after it finishes.
- [ ] Click Quit NetScope; `POST /api/shutdown` succeeds and the port lock file
      is removed.
- [ ] Ctrl+C in `--no-browser` mode exits cleanly and releases the lock.

## 2. Connectivity failures

For each scenario, note the failing layer, the catalog repair offered, and the
result after applying the repair.

- [ ] Disable the active adapter in Device Manager / Settings. Adapter and
      services layers fail with an actionable cause; re-enabling resolves it.
- [ ] Unplug the Ethernet cable (or disconnect Wi-Fi). Media-disconnected
      handling does not report a false driver error.
- [ ] Assign a static IP outside the subnet without changing the gateway.
      Gateway/LAN checks fail and the preview shows the exact `netsh`/PowerShell
      command before applying anything.
- [ ] Remove the default gateway. `IP-05`/`IP-09` offer the one-click gateway
      configuration; verify the detected gateway and rollback.
- [ ] Set a wrong static DNS server. DNS fails while raw-IP ping works; the DNS
      repair restores the previous servers.
- [ ] Stop `Dnscache` (services.msc). The service check warns/fails and the
      catalog points at `SVC-*`; starting it again resolves the check.
- [ ] Block DNS at the VM's virtual firewall/router (or point it at a blackhole
      resolver). The diagnosis reports DNS failure with internet ping working.
- [ ] Add a bogus `hosts` entry. The hosts-file check reports it; the repair
      backs up `hosts` before changing it and can be rolled back.
- [ ] Set a proxy or break WinHTTP proxy settings. Proxy checks catch it and the
      reset repair restores direct access.
- [ ] Block the gateway's ICMP but leave internet working. Gateway failure is
      reported as probable, not as a definitive diagnosis.
- [ ] Create a stale persistent route to a private subnet. Route checks flag it;
      rollback restores the route.
- [ ] Use a smaller MTU (for example 1400) on the VM NIC. `netscope mtu` finds
      the reduced path MTU and the MTU check explains it.

## 3. Fix flow and safety

- [ ] `netscope fix <id> --dry-run` prints the finding, cause, exact commands,
      admin/risk/reboot flags, snapshot plan, and rollback notes, and changes
      nothing.
- [ ] Decline the confirmation; no command runs and no backup is written.
- [ ] Run a normal-risk fix with `--yes`; verify the pre-fix snapshot, the
      step-by-step output, the re-check, and the final status.
- [ ] Run a high-risk step without `--yes-i-understand-risk`; it must refuse.
      With the flag, the typed/second confirmation still appears.
- [ ] Run a DETECT-ONLY finding; no executor step runs and the unresolved panel
      explains what to check next.
- [ ] Roll back the fix and confirm the original settings are restored.
- [ ] Delete the network connection midway through a fix; the executor reports
      an honest error, not success.
- [ ] As a non-admin, try an admin-only fix; it reports exit 4 and the exact
      elevated command, or offers UAC relaunch.

## 4. Unresolved and if-unresolved

- [ ] Cause an upstream outage the local fixes cannot repair (for example block
      the router's WAN port or unplug the VM's upstream link).
- [ ] Exhaust the ladder; confirm the "Still not working?" section asks whether
      another device works.
- [ ] Answer Yes, No, and Not sure; the ranked probable causes and next checks
      change plausibly and use probabilistic wording.
- [ ] Confirm the report includes unresolved sections and the exit code is 2.
- [ ] Confirm the web UI shows the same ranked causes, checklist, and evidence
      without raw JSON.

## 5. CLI shell, monitor, logs, reports

- [ ] `help`, numbered `menu`, `monitor`, and `exit` work in the shell.
- [ ] `monitor` updates live; `q` quits; `i` changes the interval; Ctrl+C
      restores the terminal.
- [ ] `logs --tail 5`, `logs --open`, and `logs --export FILE` work.
- [ ] `report --format txt`, `report --format json`, and `report --output -`
      write/print the expected report.
- [ ] Pipe `diagnose` and `monitor` to a file/no TTY: no ANSI prompts, no
      interactive confirmation hang.
- [ ] Use `NO_COLOR=1`; output has no ANSI escapes.

## 6. Web UI flows

- [ ] Boot URL redirects to the dashboard with a session cookie; reloading
      keeps the session.
- [ ] Open the UI with no cookie in a new private window; it is rejected and
      does not leak diagnostics.
- [ ] Run a full diagnosis and a single check; only the selected row updates
      for the single check.
- [ ] Stop the server during a run; the browser shows a reconnect/error state
      and the job can be re-polled after restart.
- [ ] Use the Repair Library search; filtering by id/name/symptom works.
- [ ] Open a repair procedure; exact commands collapse/expand; verification,
      rollback, and if-unresolved sections render.
- [ ] Preview, dry-run, and execute a fix from the UI; the APPLYING FIX progress
      bar and per-step chips appear, followed by the structured outcome.
- [ ] Trigger a Risk H fix; the typed confirmation is required.
- [ ] Cancel a tool job; the subprocess and its children stop.
- [ ] Copy/export network info and utility output; toasts confirm the action.
- [ ] Speed test asks first, transfers up to 10 MiB down and 2 MiB up, and
      reports latency/download/upload.
- [ ] Resize to mobile width; the sidebar drawer, backdrop, and nav toggle work
      with keyboard focus.
- [ ] Use the UI with the network cable unplugged; local assets still render
      (no CDN dependency).
- [ ] Press Quit NetScope; the server exits and the page no longer loads.
- [ ] As a non-admin, confirm the banner/status chip and the
      "Restart as administrator" action (decline UAC and confirm the server
      stays alive).
- [ ] Accept UAC from "Restart as administrator"; the elevated server waits for
      the old lock, takes over with `--replace`, and the page reconnects.
- [ ] `POST /api/*` with a missing/incorrect token or foreign Origin is rejected.

## 7. Installer lifecycle

### Inno Setup installer

- [ ] `scripts\build_installer.ps1` reads `config.APP_VERSION` and writes
      `dist\installer\NetScope-Setup.exe`; `-Version X.Y.Z` overrides it.
- [ ] Run the setup interactively on a clean VM/profile: defaults to
      `%LOCALAPPDATA%\Programs\NetScope`, requires no admin, offers the optional
      desktop shortcut, and launches NetScope at the end.
- [ ] With WebView2 present, setup does not download it; with it absent (or on
      an offline VM), setup uses the bundled bootstrap/offline installer.
- [ ] Start Menu shortcut opens the app window; `netscope --version` resolves
      from a new terminal.
- [ ] `.netscope-inno` exists in the install directory.
- [ ] `NetScope.exe install --dry-run` and `NetScope.exe uninstall` refuse to
      modify the Inno-managed install and point to **Settings > Apps**.
- [ ] Run `python scripts\installer_smoke.py --installer dist\installer\NetScope-Setup.exe`
      in a disposable profile; it verifies shortcut, App Paths, PATH, version,
      uninstall, and default data removal.
- [ ] Uninstall from **Settings > Apps**; the app, shortcut, PATH entry and App
      Paths key are removed.
- [ ] Uninstall data prompt opens with **Yes** selected; accept it and confirm
      `%LOCALAPPDATA%\NetScope` is removed. Repeat and choose **No**: data stays.
- [ ] Reinstall over an existing Inno install; the version upgrades and user
      data is preserved.

### Portable CLI installer

- [ ] `NetScope.exe install --dry-run` lists the copy, PATH, App Paths, and
      shortcut actions without changing anything.
- [ ] `NetScope.exe install` copies to
      `%LOCALAPPDATA%\Programs\NetScope\NetScope.exe`, adds the directory to the
      user PATH, registers App Paths, creates the Start Menu shortcut, and
      writes `.netscope-install`.
- [ ] Open a new terminal; `netscope --version` resolves from PATH.
- [ ] Win+R `NetScope` launches the app.
- [ ] Run install twice; the PATH entry is not duplicated and the second run
      still succeeds.
- [ ] Put an unrelated file in the install directory; uninstall keeps it and
      removes only the exe/marker/shortcut.
- [ ] `NetScope.exe uninstall` removes PATH, App Paths, shortcut, and files.
- [ ] `NetScope.exe uninstall --purge` also removes
      `%LOCALAPPDATA%\NetScope` (logs/reports/backups).
- [ ] Kill the server before uninstall; uninstall still works, and a second
      uninstall is harmless.
- [ ] Install from a copied exe with `--source PATH`; the installed copy runs.
- [ ] Install to a custom absolute directory with `--dir PATH`; uninstall with
      the same `--dir`.
