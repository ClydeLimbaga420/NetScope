# Notes

- 2026-11-17: Legacy-dashboard removal Phase 1 complete; characterized the successful localhost `/api/status`, `/api/devices`, and `/api/packet-loss` payload contracts. Phase 2 is next.
- 2026-11-17: Legacy-dashboard removal Phase 2 complete; added shared monitoring/status and packet-loss sampling, defensive ping-stat parsing, bounded local device discovery, and permanent-MAC snapshot data. Focused tests: 32 passed. Full suite: 317 passed, 1 failed, 3 skipped; the one failure is the pre-existing stylesheet-copy mismatch in untouched `static/css/style.css` and `web/static/css/style.css`. Phase 3 is next; legacy dashboard files remain untouched.
