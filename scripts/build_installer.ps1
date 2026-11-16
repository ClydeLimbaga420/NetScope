<#
.SYNOPSIS
    Build dist\installer\NetScope-Setup.exe with Inno Setup.

.DESCRIPTION
    Uses the project's virtual environment to read config.APP_VERSION unless
    -Version is supplied. Finds ISCC.exe on PATH or under the usual Inno Setup 6/7
    install directories.

.PARAMETER Version
    Override the installer version. Defaults to config.APP_VERSION.

.PARAMETER Python
    Python executable used to read the version. Defaults to the project venv.
#>
param(
    [string]$Version,
    [string]$Python
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

    if (-not $Version) {
        $Version = (& $Python -c "import config; print(config.APP_VERSION)").Trim()
        if ($LASTEXITCODE -ne 0 -or -not $Version) {
            throw "Could not read config.APP_VERSION with $Python"
        }
    }

    $iscc = $null
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) {
        $iscc = $command.Source
    }
    if (-not $iscc) {
        $candidates = @(
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe")
        )
        foreach ($candidate in $candidates) {
            if ($candidate -and (Test-Path -LiteralPath $candidate)) {
                $iscc = $candidate
                break
            }
        }
    }
    if (-not $iscc) {
        throw "Inno Setup (ISCC.exe) not found. Install Inno Setup 6 or 7."
    }

    $icon = Join-Path $root "assets\netscope.ico"
    $iconScript = Join-Path $root "build_icon.py"
    if (-not (Test-Path -LiteralPath $icon) -and (Test-Path -LiteralPath $iconScript)) {
        & $Python $iconScript
        if ($LASTEXITCODE -ne 0) {
            throw "Icon generation failed with exit code $LASTEXITCODE"
        }
    }
    if (-not (Test-Path -LiteralPath $icon)) {
        throw "Icon not found: $icon (run build_icon.py)"
    }

    $script = Join-Path $root "installer\NetScope.iss"
    if (-not (Test-Path -LiteralPath $script)) {
        throw "Installer script not found: $script"
    }

    & $iscc "/DAppVersion=$Version" $script
    if ($LASTEXITCODE -ne 0) {
        throw "ISCC.exe failed with exit code $LASTEXITCODE"
    }

    $setup = Join-Path $root "dist\installer\NetScope-Setup.exe"
    if (-not (Test-Path -LiteralPath $setup)) {
        throw "Build finished but $setup is missing"
    }
    $size = (Get-Item -LiteralPath $setup).Length
    Write-Host ("Built {0} ({1:N1} MB)" -f (Resolve-Path $setup), ($size / 1MB))
} finally {
    Pop-Location
}
