# Editable install (creates `netscope` command)
.\.venv\Scripts\pip.exe install -e .
.\.venv\Scripts\netscope.exe gui //alternative
# Now just type
netscope --help
netscope gui
netscope diagnose --json

add speed test