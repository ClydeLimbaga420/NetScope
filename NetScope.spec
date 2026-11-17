# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file, windowed-subsystem build for NetScope.

A double-click opens the web UI without creating a console (so Windows Terminal
never adds a taskbar button for it). ``cli.launch.attach_parent_console()``
reattaches CLI output when the exe is run from a terminal, and redirected
stdout/stderr pipes keep working for smoke tests. Web templates/static and the
fix catalog are bundled next to the extracted package; web/paths.py resolves
them through sys._MEIPASS.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH)

web = project_root / "web"
fixes = project_root / "fixes"
core = project_root / "core"

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
        (str(core / "oui_vendors.json"), "core"),
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
