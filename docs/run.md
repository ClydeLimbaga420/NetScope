# Editable install (creates `netscope` command)
.\.venv\Scripts\pip.exe install -e .
.\.venv\Scripts\netscope.exe gui //alternative
# Now just type
netscope --help
netscope gui
netscope diagnose --json

In the web GUI, choose **Run as administrator** and approve the Windows UAC
prompt. NetScope restarts elevated and automatically switches the current
browser tab to the administrator session. If elevation is cancelled or fails,
the existing session stays open. This also works when Windows asks for
credentials for a different administrator account, without leaving an extra
console window open.

In the web GUI, open Troubleshoot and choose **Speed test** in the network
tools. It reports HTTP latency plus download and upload throughput using
Cloudflare's public test endpoint. Each run transfers up to 10 MiB down and
2 MiB up; the GUI asks before starting. An internet connection is required.

add speed test