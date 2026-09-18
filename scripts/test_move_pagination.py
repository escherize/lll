#!/usr/bin/env python3
"""A later-page reference must prevent project/label scope changes."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.parse

binary = str(Path(sys.argv[1]).resolve())
alpha = {'id': 'teamalpha000001', 'key': 'ALPHA', 'name': 'Alpha'}
beta = {'id': 'teambeta0000001', 'key': 'BETA', 'name': 'Beta'}


class API(http.server.BaseHTTPRequestHandler):
    size = 201
    placement = 'last'
    fail = ''
    calls = []
    patches = []

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        collection = parsed.path.split('/')[3]
        page = int(q.get('page', ['1'])[0])
        limit = int(q.get('perPage', ['30'])[0])
        self.calls.append((collection, page, q))
        if collection == 'teams':
            rows = [alpha] if 'ALPHA' in q['filter'][0] else [beta]
        elif collection in ('projects', 'labels'):
            rows = [{'id': 'sharedentity001', 'name': 'Shared', 'team': alpha['id'], 'expand': {'team': alpha}}]
        else:
            if self.fail and page == 2:
                self.send_response(500 if self.fail == 'http' else 200)
                self.end_headers()
                self.wfile.write(b'{"message":"fixture reference page refused"}' if self.fail == 'http' else b'{bad page')
                return
            rows = []
            for i in range(self.size):
                blocked = self.placement == 'all' or (self.placement == 'last' and i == self.size - 1)
                team = alpha if blocked else beta
                rows.append({'id': f'{i:015}', 'team': team['id'], 'number': i + 1, 'expand': {'team': team}})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'items': rows[(page - 1) * limit:page * limit],
                                    'totalItems': len(rows), 'totalPages': (len(rows) + limit - 1) // limit}).encode())

    def do_PATCH(self):
        self.patches.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{}')

    def log_message(self, *_):
        pass


with tempfile.TemporaryDirectory(prefix='lll-move-pages-') as directory:
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), API)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
    env.update(HOME=directory, LLL_CONFIG_HOME=directory + '/config',
               LLL_URL=f'http://127.0.0.1:{server.server_port}',
               LLL_TOKEN='fake-move-pages-token', LLL_TEAM='ALPHA')

    def run(noun, destination='BETA'):
        API.calls = []
        API.patches = []
        return subprocess.run([binary, noun, 'move', 'Shared', '--to', destination],
                              cwd=directory, env=env, text=True, capture_output=True, timeout=15)

    try:
        for noun in ('project', 'label'):
            API.placement = 'last'
            for size in (201, 501):
                API.size = size
                result = run(noun)
                assert result.returncode != 0 and not result.stdout and not API.patches, result
                assert f'ALPHA-{size}' in result.stderr and 'stays in ALPHA' in result.stderr, result.stderr
                calls = [(p, q) for c, p, q in API.calls if c == 'issues']
                assert len(calls) == (size + 499) // 500, calls
                for _, q in calls:
                    assert q['expand'] == ['team'] and q['sort'] == ['created,id'], q
                    assert 'sharedentity001' in q['filter'][0], q
                    assert ('labels.id ?=' if noun == 'label' else 'project=') in q['filter'][0], q
            API.placement = 'all'
            result = run(noun)
            assert result.returncode != 0 and not API.patches
            assert '501 issue(s)' in result.stderr and '(and 491 more)' in result.stderr, result.stderr
            API.placement = 'none'
            for failure in ('http', 'decode'):
                API.fail = failure
                result = run(noun)
                assert result.returncode != 0 and not result.stdout and not API.patches, result
                assert ('fixture reference page refused' if failure == 'http' else 'decoding issues') in result.stderr, result.stderr
            API.fail = ''
            for size in (0, 501):
                API.size = size
                result = run(noun)
                assert result.returncode == 0 and 'Moved ' in result.stdout, result
                assert API.patches == [(f'/api/collections/{noun}s/records/sharedentity001', {'team': beta['id']})], API.patches
            result = run(noun, 'ALPHA')
            assert result.returncode == 0 and 'already in ALPHA' in result.stdout and not API.patches, result
            assert not any(c == 'issues' for c, _, _ in API.calls), API.calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
print('Move pagination: both nouns refuse later-page blockers/read failures without PATCH; complete counts, safe/unused/already-scoped moves and filters preserved')
