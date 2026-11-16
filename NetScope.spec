# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file, console-subsystem build for NetScope.

The executable stays console-subsystem so the CLI works, and detaches its own
console when it opens the web UI (see cli/launch.py). Web templates/static and
the fix catalog are bundled next to the extracted package; web/paths.py resolves
them through sys._MEIPASS.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH)

web = project_root / "web"
fixes = project_root / "fixes"

webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")
webview_hiddenimports = [
    name
    for name in webview_hiddenimports
    if not name.startswith("webview.platforms.android")
]
pythonnet_datas, pythonnet_binaries, pythonnet_hiddenimports = collect_all("pythonnet")
clr_loader_datas, clr_loader_binaries, clr_loader_hiddenimports = collect_all("clr_loader")

hiddenimports = [
    "flask",
    "werkzeug",
    "jinja2",
    "psutil",
    "requests",
    "modules.network_info",
    "modules.bandwidth",
    "modules.ping_monitor",
    "modules.device_scanner",
    "modules.diagnostics",
    "modules.oui_vendors",
    "fixes.gateway_config",
    "web.api",
    "web.jobs",
    "web.pages",
    "web.paths",
    "web.run",
    "web.runtime",
    "web.security",
    "web.server",
    "web.window",
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "pythonnet",
    "clr",
    "clr_loader",
] + webview_hiddenimports + pythonnet_hiddenimports + clr_loader_hiddenimports

excludes = [
    "tkinter",
    "PyQt5",
    "PySide6",
    "matplotlib",
    "numpy",
    "IPython",
    "pytest",
    "pip",
    "setuptools",
    "wheel",
]

a = Analysis(
    [str(project_root / "netscope.py")],
    pathex=[str(project_root)],
    binaries=webview_binaries + pythonnet_binaries + clr_loader_binaries,
    datas=[
        (str(web / "templates"), "web/templates"),
        (str(web / "static"), "web/static"),
        (str(fixes / "fixes.json"), "fixes"),
    ] + webview_datas + pythonnet_datas + clr_loader_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NetScope",
    icon=str(project_root / "assets" / "netscope.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
