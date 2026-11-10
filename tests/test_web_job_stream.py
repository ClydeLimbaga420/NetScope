from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
SCRIPT = Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "job-stream.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")


def run_node(harness: str) -> None:
    source_path = json.dumps(str(SCRIPT))
    script = f"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync({source_path}, 'utf8');
{harness}
"""
    result = subprocess.run(
        [NODE, "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_eventsource_error_falls_back_to_job_polling():
    run_node(r"""
const window = {};
window.EventSource = class {
  constructor(url) { this.url = url; window.source = this; }
  close() { this.closed = true; }
};
const context = { window, encodeURIComponent, setTimeout, Promise, JSON, Set };
vm.runInNewContext(source, context);
let requests = 0;
let recovered = null;
const followed = window.NetScopeJobStream.follow('job/1', {
  request: async (url) => {
    assert.strictEqual(url, '/api/jobs/job%2F1');
    requests += 1;
    return requests === 1
      ? { status: 'running' }
      : { status: 'done', result: { ok: true } };
  },
  onFallback: (job) => { recovered = job.result; },
  pollInterval: 1,
});
assert.strictEqual(window.source.url, '/api/jobs/job%2F1/events');
window.source.onerror();
followed.then((job) => {
  assert.strictEqual(window.source.closed, true);
  assert.strictEqual(job.status, 'done');
  assert.deepStrictEqual(job.result, { ok: true });
  assert.deepStrictEqual(recovered, { ok: true });
  assert.strictEqual(requests, 2);
}).catch((error) => { console.error(error); process.exitCode = 1; });
""")


def test_missing_eventsource_uses_polling_directly():
    run_node(r"""
const window = {};
const context = { window, encodeURIComponent, setTimeout, Promise, JSON, Set };
vm.runInNewContext(source, context);
let recovered = null;
window.NetScopeJobStream.follow('job-2', {
  request: async () => ({ status: 'done', result: { value: 7 } }),
  onFallback: (job) => { recovered = job.result; },
}).then((job) => {
  assert.strictEqual(job.status, 'done');
  assert.deepStrictEqual(recovered, { value: 7 });
}).catch((error) => { console.error(error); process.exitCode = 1; });
""")
