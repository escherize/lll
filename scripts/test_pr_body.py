#!/usr/bin/env python3
"""Exercise PR body transport with a real issue API and a recording gh."""
import json
import http.server
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.request

binary, api = sys.argv[1:]
binary = str(Path(binary).resolve())
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    gh = root / 'gh'
    gh.write_text(f'#!{sys.executable}\n' + '''import json,os,pathlib,sys
pathlib.Path(os.environ['PR_CAPTURE']).write_text(json.dumps({'args':sys.argv[1:],'body':sys.stdin.read()}))
print(os.environ.get('PR_OUTPUT', 'https://github.example/owner/repo/pull/1'))
sys.exit(int(os.environ.get('PR_EXIT', '0')))
''')
    gh.chmod(0o755)
    capture = root / 'capture.json'
    env = dict(os.environ, HOME=directory, LLL_URL=api, LLL_TEAM='ENG',
               LLL_WEB_URL='https://board.example', PR_CAPTURE=str(capture),
               PATH=directory + os.pathsep + os.environ['PATH'])

    def run(*args, body=None, extra=None):
        return subprocess.run([binary, *args], input=body, env=dict(env, **(extra or {})),
                              cwd=directory, capture_output=True, text=True, timeout=20)

    # The 40k emoji body exceeds Linux's single-argument byte ceiling while
    # staying below the PR character limit. The marker must remain literal.
    for description in ('', 'Quotes " and $() `literal`\n\nline two', '🧪' * 40000, 'x' * 100000):
        description_flags = ['-d', '-'] if description else []
        created = run('issue', 'create', 'PR body fixture', *description_flags, '--json', body=description)
        assert created.returncode == 0, created.stderr
        record = json.loads(created.stdout)
        key = f'ENG-{record["number"]}'
        seeded = run('issue', 'ref', key, 'linear:ENG-118')
        assert seeded.returncode == 0, seeded.stderr
        result = run('issue', 'pr', key)
        assert result.returncode == 0, result.stderr
        payload = json.loads(capture.read_text())
        assert payload['args'] == ['pr', 'create', '--title', f'{key}: PR body fixture', '--body-file', '-'], payload['args']
        link = f'https://board.example/issue/{key}'
        expected = link + ('\n\n' + description if description else '')
        if len(expected) <= 65536:
            assert payload['body'] == expected
            assert 'exceeds' not in result.stderr
        else:
            assert payload['body'].startswith(link + '\n\n')
            assert 'full description' in payload['body']
            assert len(payload['body']) <= 65536
            assert 'linking to the full description' in result.stderr
        assert 'https://github.example/owner/repo/pull/1' in result.stdout
        saved = json.loads(run('issue', 'view', key, '--json').stdout)
        assert saved['refs'] == 'linear:ENG-118 gh#1'

    before = json.loads(run('issue', 'view', key, '--json').stdout)
    duplicate = run('issue', 'ref', key, 'gh#1')
    assert duplicate.returncode == 0 and 'Already recorded' in duplicate.stdout
    assert json.loads(run('issue', 'view', key, '--json').stdout) == before
    # A lone positional is ambiguous: refs are KEY-shaped too and there is no unref.
    for lone in [(key,), ('gh#1',), ('linear:ENG-118',)]:
        refused = run('issue', 'ref', *lone)
        assert refused.returncode != 0, refused
        assert 'usage: lll issue ref KEY-123 REF' in refused.stderr, refused.stderr
    assert json.loads(run('issue', 'view', key, '--json').stdout) == before

    failed = run('issue', 'pr', key, extra={'PR_EXIT': '7'})
    assert failed.returncode != 0 and 'gh pr create' in failed.stderr, failed
    assert json.loads(run('issue', 'view', key, '--json').stdout) == before
    ambiguous = run('issue', 'pr', key, extra={'PR_OUTPUT': 'https://github.example/o/r/pull/2\nhttps://github.example/o/r/pull/3'})
    assert ambiguous.returncode != 0 and 'unambiguous' in ambiguous.stderr
    assert json.loads(run('issue', 'view', key, '--json').stdout) == before
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda number: run('issue', 'ref', key, f'gh#{number}'), range(2, 18)))
    assert all(result.returncode == 0 for result in results), [result.stderr for result in results]
    saved = json.loads(run('issue', 'view', key, '--json').stdout)
    assert set(saved['refs'].split()) == {'linear:ENG-118', *(f'gh#{number}' for number in range(1, 18))}
    assert saved['title'] == before['title'] and saved['description'] == before['description']

    class RefFailure(http.server.BaseHTTPRequestHandler):
        status = 503
        writes = 0
        def do_GET(self):
            req = urllib.request.Request(api + self.path,
                headers={'Authorization': self.headers.get('Authorization', '')})
            with urllib.request.urlopen(req, timeout=10) as response:
                self.send_response(response.status); self.end_headers(); self.wfile.write(response.read())
        def do_POST(self):
            assert self.path.endswith('/refs'), self.path
            type(self).writes += 1
            self.send_response(self.status); self.end_headers()
            self.wfile.write(b'{"message":"reference write unavailable"}')
        def log_message(self, *args): pass

    proxy = http.server.ThreadingHTTPServer(('127.0.0.1', 0), RefFailure)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        for status in [503, 404]:
            RefFailure.status = status
            result = run('issue', 'pr', key, extra={
                'LLL_URL': f'http://127.0.0.1:{proxy.server_port}',
                'PR_OUTPUT': 'https://github.example/owner/repo/pull/19'})
            assert result.returncode != 0
            assert 'https://github.example/owner/repo/pull/19' in result.stdout
            assert 'PR created:' in result.stderr and f'lll issue ref {key} gh#19' in result.stderr
            assert json.loads(run('issue', 'view', key, '--json').stdout) == saved
        assert RefFailure.writes == 2, 'unexpected retries or legacy fallback'
    finally:
        proxy.shutdown(); proxy.server_close()
    recovered = run('issue', 'ref', key, 'gh#19')
    assert recovered.returncode == 0, recovered.stderr
    assert 'gh#19' in json.loads(run('issue', 'view', key, '--json').stdout)['refs'].split()
print('PR bodies: exact stdin transport, large Unicode, oversized link fallback and gh failure passed')
print('PR refs: success, unchanged failure/ambiguity, duplicate/concurrent preservation, lone-argument refusal, failed-save recovery and old-server refusal passed')
