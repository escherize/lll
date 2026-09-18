#!/usr/bin/env python3
"""Read-only benchmark: mise exec -- python3 scripts/measure_issue_view.py API KEY OLD NEW."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

api, key, old, new = sys.argv[1:]
old, new = os.path.abspath(old), os.path.abspath(new)
with tempfile.TemporaryDirectory(prefix='lll-view-measure-') as directory:
    directory = Path(directory)
    helper = directory / 'proxy'
    address = directory / 'address'
    subprocess.run(['go', 'build', '-o', str(helper), str(Path(__file__).with_name('issue_view_proxy.go'))], check=True)
    process = subprocess.Popen([str(helper), api, str(address)])
    try:
        for _ in range(100):
            if address.exists():
                break
            assert process.poll() is None, 'Counting proxy stopped before startup'
            time.sleep(0.05)
        proxy = address.read_text()

        def get(path):
            with urllib.request.urlopen(proxy + path, timeout=30) as response:
                return response.read()

        # Keep the upstream TLS connection warm for both binaries equally.
        get('/api/health')
        env = dict(os.environ, LLL_URL=proxy)
        env.pop('LLL_TOKEN_PROBED', None)
        rows = []
        for mode, flags in [('view', []), ('raw', ['--raw']), ('json', ['--json'])]:
            pairs = []
            for _ in range(3):
                for label, binary in [('before', old), ('after', new)]:
                    get('/__reset')
                    started = time.perf_counter()
                    result = subprocess.run([binary, 'issue', 'view', key, *flags], env=env,
                                            capture_output=True, text=True, timeout=30)
                    elapsed = time.perf_counter() - started
                    assert result.returncode == 0, result.stderr
                    events = json.loads(get('/__stats'))
                    probes = sum('/members/records/' in event['path'] for event in events)
                    row = dict(mode=mode, binary=label, seconds=round(elapsed, 3),
                               requests=len(events), member_probes=probes)
                    rows.append(row)
                    print(json.dumps(row), flush=True)
                    pairs.append((label, result.stdout))
                before, after = pairs[-2][1], pairs[-1][1]
                if mode == 'view':
                    before = re.sub(r'\b\d+[mhd] ago\b|just now', '<age>', before)
                    after = re.sub(r'\b\d+[mhd] ago\b|just now', '<age>', after)
                assert before == after, mode + ' output changed'
        print(json.dumps({'measurements': rows}), flush=True)
    finally:
        process.terminate()
        process.wait(timeout=5)
