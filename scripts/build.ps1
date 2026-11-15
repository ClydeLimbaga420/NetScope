<#
.SYNOPSIS
    Build dist\NetScope.exe with PyInstaller.

.DESCRIPTION
    Uses the project's virtual environment when present. The build is a
    one-file, console-subsystem executable that bundles web templates/static and
    the fix catalog.

.PARAMETER Python
    Python executable to use. Defaults to .venv\Scripts\python.exe when
    available, otherwise python on PATH.

.PARAMETER Clean
    Remove the PyInstaller build cache before building.

.PARAMETER DistPath
    Output directory for NetScope.exe. Defaults to dist. Use "." to place the
    executable in the repository root.
#>
param(
    [string]$Python,
    [switch]$Clean,
    [string]$DistPath = "dist"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (-not $Python) {
        $venvPython = Join-Path $root ".venv\Scripts\python.exe"
        if (Test-Path -LiteralPath $venvPython) {
            $Python = $venvPython
        } else {
            $Python = "python"
        }
    }

    & $Python -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed. Run: $Python -m pip install pyinstaller"
    }

    $arguments = @(
        "-m", "PyInstaller", "--noconfirm",
        "--distpath", $DistPath,
        "NetScope.spec"
    )
    if ($Clean) {
        $arguments = @(
            "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", $DistPath,
            "NetScope.spec"
        )
    }

    & $Python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    $exe = Join-Path $DistPath "NetScope.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Build finished but $exe is missing"
    }
    $size = (Get-Item -LiteralPath $exe).Length
    Write-Host ("Built {0} ({1:N1} MB)" -f (Resolve-Path $exe), ($size / 1MB))
} finally {
    Pop-Location
}
