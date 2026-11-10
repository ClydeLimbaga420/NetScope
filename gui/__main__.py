"""Developer entry point: ``python -m gui`` runs the GUI in this process.

The console stays attached here (closing it exits the GUI). The blessed
launcher is ``netscope gui``, which spawns the GUI detached instead.
"""

from __future__ import annotations

from gui.app import run_gui

if __name__ == "__main__":
    raise SystemExit(run_gui())
