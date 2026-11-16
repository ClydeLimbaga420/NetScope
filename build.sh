#!/usr/bin/env bash
set -euo pipefail

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) ;;
    *)
        echo "This script builds the Windows executable; run it from Git Bash on Windows." >&2
        exit 1
        ;;
esac

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

if [[ -n "${PYTHON:-}" ]]; then
    python_cmd=("$PYTHON")
elif command -v py >/dev/null 2>&1; then
    python_cmd=(py -3)
elif command -v python >/dev/null 2>&1; then
    python_cmd=(python)
else
    echo "Python was not found. Install Python or set PYTHON to its executable." >&2
    exit 1
fi

"${python_cmd[@]}" -m pip install -r requirements.txt
"${python_cmd[@]}" -m pip install pyinstaller
"${python_cmd[@]}" -m PyInstaller --noconfirm --clean --distpath dist NetScope.spec

if [[ ! -f dist/NetScope.exe ]]; then
    echo "Build finished, but dist/NetScope.exe was not created." >&2
    exit 1
fi

if ! app_version="$("${python_cmd[@]}" -c "import config; print(config.APP_VERSION)")"; then
    echo "Could not read the app version with the selected Python." >&2
    exit 1
fi

if [[ -n "${POWERSHELL:-}" ]]; then
    powershell_cmd="$POWERSHELL"
elif command -v powershell.exe >/dev/null 2>&1; then
    powershell_cmd="powershell.exe"
elif command -v powershell >/dev/null 2>&1; then
    powershell_cmd="powershell"
else
    echo "PowerShell was not found; it is required to build the installer." >&2
    exit 1
fi

"$powershell_cmd" -NoProfile -ExecutionPolicy Bypass \
    -File scripts/build_installer.ps1 -Version "$app_version"

if [[ ! -f dist/installer/NetScope-Setup.exe ]]; then
    echo "Installer build finished, but dist/installer/NetScope-Setup.exe was not created." >&2
    exit 1
fi

echo "Built $repo_root/dist/installer/NetScope-Setup.exe"
