# Editable install (creates `netscope` command)
.\.venv\Scripts\pip.exe install -e .
# Now just type
netscope --help
netscope gui
netscope diagnose --json