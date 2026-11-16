# Building NetScope

## Requirements

- Windows 10 or later, x64
- Git Bash
- Python 3 available as `py -3` or `python`
- PowerShell
- Inno Setup 6 or 7, with `ISCC.exe` in `PATH` or a standard install location
- Internet access for the script's pip installs

## Build the executable and installer

Open cli in the repository root and run:

```bash
bash build.sh
```

[`build.sh`](../build.sh) installs the packages from `requirements.txt` and
PyInstaller, builds the one-file executable with [`NetScope.spec`](../NetScope.spec),
then runs the Inno Setup compiler through
[`scripts/build_installer.ps1`](../scripts/build_installer.ps1).

The script selects Python in this order:

1. The `PYTHON` environment variable, if set
2. `py -3`, if available
3. `python`

Set `PYTHON` to choose another interpreter. Set `POWERSHELL` to override the
PowerShell executable.

The outputs are:

- `dist\NetScope.exe` — the console-subsystem executable, which supports both
  the CLI and the GUI launch behavior
- `dist\installer\NetScope-Setup.exe` — the per-user Inno Setup installer

The script recreates `dist` if needed and overwrites the build outputs. You do
not need to delete `dist` first. Building does not install or update NetScope;
run the resulting setup executable to install it.

## Verify the build

The build script does not run tests or smoke checks. After it completes, verify
the packaged executable with:

```bash
python scripts/frozen_smoke.py --exe dist/NetScope.exe
```

The smoke test checks that the frozen app serves the local UI and shuts down
cleanly. To verify the CLI entry point separately:

```bash
dist/NetScope.exe --version
```

## Build only the executable

To build the executable without building the installer, use PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Clean
```

See the [README build section](../README.md#building-the-executable) for
alternative output paths and installer smoke-test details.
