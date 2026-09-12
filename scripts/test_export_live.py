#!/usr/bin/env python3
"""Full export through the real CLI, with more than one server page."""
from concurrent.futures import ThreadPoolExecutor
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
env = dict(os.environ, LLL_BIN=binary, LLL_URL=api, LLL_TEAM='EXPT')
exporter = str(Path('bin/lll-export').resolve())


def cli(*args):
    return subprocess.check_output([binary, *args], env=env, text=True, timeout=30)


def post(collection, body):
    request = urllib.request.Request(api + '/api/collections/' + collection + '/records',
        data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + env['LLL_TOKEN'], 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


team = post('teams', {'key': 'EXPT', 'name': 'Export verification'})
with ThreadPoolExecutor(max_workers=6) as pool:
    created = list(pool.map(lambda n: post('issues', {'team': team['id'], 'title': f'Export evidence {n}',
        'state': 'todo', 'description': f'Greppable Unicode evidence café {n}'}), range(201)))
cli('doc', 'create', '-s', 'export-evidence', '-t', 'Export evidence', '-b', 'Offline document evidence')
first = json.loads(cli('issue', 'list', '--json', '--page', '1'))
second = json.loads(cli('issue', 'list', '--json', '--page', '2'))
assert len(first['items']) == 200 and len(second['items']) == 1
assert {i['id'] for i in first['items'] + second['items']} == {i['id'] for i in created}
assert json.loads(cli('issue', 'list', '--json', '--page', '3'))['items'] == []
for invalid in ['0', '-1', 'abc', '999999999999999999999999999']:
    p = subprocess.run([binary, 'issue', 'list', '--page', invalid], env=env, text=True, capture_output=True)
    assert p.returncode != 0 and '--page must be a positive integer' in p.stderr


class FailSecondPage(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == '/api/collections/issues/records' and urllib.parse.parse_qs(parsed.query).get('page') == ['2']:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"message":"export page unavailable"}')
            return
        request = urllib.request.Request(api + self.path, headers={'Authorization': self.headers.get('Authorization', '')})
        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.send_response(response.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(response.read())


with tempfile.TemporaryDirectory(prefix='lll-export-test-') as directory:
    target = Path(directory) / 'mirror with spaces'
    p = subprocess.run([exporter, str(target)], env=env, text=True, capture_output=True, timeout=120)
    assert p.returncode == 0, p.stderr
    expected = {f'EXPT-{i["number"]}.md' for i in created}
    assert {f.name for f in (target/'issues').iterdir()} == expected
    assert 'Offline document evidence' in (target/'docs/export-evidence.md').read_text()
    assert 'Greppable Unicode evidence café' in next((target/'issues').iterdir()).read_text()
    before = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob('*') if p.is_file()}
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FailSecondPage)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        proxy = f'http://127.0.0.1:{server.server_port}'
        p = subprocess.run([exporter, str(target)], env=dict(env, LLL_URL=proxy), text=True, capture_output=True, timeout=30)
        assert p.returncode != 0 and '503' in p.stderr, p.stderr
        after = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob('*') if p.is_file()}
        assert after == before, 'failed later page changed the previous mirror'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
print('Export: 201 real issues, docs, Unicode and spaced paths; explicit pages and rejected pages; failed later page preserves the entire mirror')
