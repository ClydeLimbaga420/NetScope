# Run NetScope

## From source

Create and install the development environment:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

Run the CLI or open the localhost web UI:

```powershell
netscope --help
netscope diagnose
netscope gui
```

`netscope gui` opens the desktop window when WebView2 is available and falls
back to the browser. Use `netscope gui --browser` to force Edge/Chrome, or
`netscope gui --no-browser --port N` to run in the foreground and print the
boot URL. The web server binds only to `127.0.0.1`; there is no LAN-hosted
dashboard.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Clean
python scripts\frozen_smoke.py --exe dist\NetScope.exe
```
