"""NetScope graphical front end (tkinter).

This package renders engine output only; diagnostics and fixes stay in
``core`` and ``fixes``. Importing ``gui`` never imports tkinter — only
``gui.app`` (and therefore ``netscope gui``/``python -m gui``) needs it.
"""
