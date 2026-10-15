#!/usr/bin/env python3
"""LLL-700: keyed comments survive retries without a duplicate, scoped per issue."""
import concurrent.futures
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
assert urllib.parse.urlsplit(api).hostname == '127.0.0.1', 'requires an isolated loopback board'
env = dict(os.environ, LLL_URL=api, LLL_TEAM='IDEMC')


def request(path, payload=None, *, method=None, token=None):
    headers = {'Authorization': 'Bearer ' + (env['LLL_TOKEN'] if token is None else token)}
    data = None if payload is None else json.dumps(payload).encode()
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(api + path, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def cli(*args, url=api, code=0):
    result = subprocess.run([binary, *args], env=dict(env, LLL_URL=url),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == code, (result.args, result.returncode, result.stdout, result.stderr)
    return result


def comments(key):
    return json.loads(cli('issue', 'comment', key, '--json').stdout)['items']


status, team = request('/api/collections/teams/records', {'key': 'IDEMC', 'name': 'Comment idempotency'})
assert status == 200, team
assert request('/api/lll/comments/idempotency')[1] == {'supported': True}
assert request('/api/lll/comments/idempotency', token='')[0] == 401
for title in ('Keyed comments', 'Another issue'):
    cli('issue', 'create', '-t', title)

# Same key and body twice: one comment, the second answer is the first.
args = ('issue', 'comment', 'IDEMC-1', '-b', 'same body', '--idempotency-key', 'k1')
first = cli(*args)
assert first.stdout.startswith('Commented on IDEMC-1'), first.stdout
again = cli(*args)
assert again.stdout.startswith('Reused the comment on IDEMC-1'), again.stdout
replay = json.loads(cli(*args, '--json').stdout)
assert replay['reused'] is True and replay['body'] == 'same body'
saved = comments('IDEMC-1')
assert [c['body'] for c in saved] == ['same body'] and saved[0]['id'] == replay['id'], saved
assert 'idempotency_key' not in saved[0] and 'idempotency_fingerprint' not in saved[0]

# Same key, changed body: a 409 conflict, exit 4, and nothing saved.
conflict = cli('issue', 'comment', 'IDEMC-1', '-b', 'changed body', '--idempotency-key', 'k1', code=4)
assert 'different creation payload' in conflict.stderr, conflict.stderr
assert len(comments('IDEMC-1')) == 1

# The key is scoped per issue: the same key elsewhere is a separate comment.
other = json.loads(cli('issue', 'comment', 'IDEMC-2', '-b', 'same body', '--idempotency-key', 'k1', '--json').stdout)
assert other['id'] != replay['id'] and 'reused' not in other
assert len(comments('IDEMC-1')) == 1 and len(comments('IDEMC-2')) == 1

# Unkeyed comments stay independent; an empty key or a key with no body is a usage error.
cli('issue', 'comment', 'IDEMC-2', '-b', 'plain')
cli('issue', 'comment', 'IDEMC-2', '-b', 'plain')
assert len(comments('IDEMC-2')) == 3
for empty in ('', '   '):
    refused = cli('issue', 'comment', 'IDEMC-1', '-b', 'x', '--idempotency-key', empty, url='http://127.0.0.1:1', code=2)
    assert '--idempotency-key must not be empty' in refused.stderr
refused = cli('issue', 'comment', 'IDEMC-1', '--idempotency-key', 'k9', url='http://127.0.0.1:1', code=2)
assert 'give its body' in refused.stderr

# Concurrent retries: one comment between them, and only one is not reused.
race = ('issue', 'comment', 'IDEMC-1', '-b', 'raced', '--idempotency-key', 'race', '--json')
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    results = list(pool.map(lambda _: json.loads(cli(*race).stdout), range(12)))
assert len({r['id'] for r in results}) == 1
assert sum(not r.get('reused', False) for r in results) == 1
assert [c['body'] for c in comments('IDEMC-1')].count('raced') == 1

state = {'mode': 'old', 'posts': 0, 'keys': [], 'committed': None, 'intercepted': False}
comment_path = '/api/collections/comments/records'


class Proxy(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def forward(self):
        parsed = urllib.parse.urlsplit(self.path)
        if state['mode'] == 'old' and parsed.path == '/api/lll/comments/idempotency':
            self.reply(404, {'message': 'not supported'})
            return
        is_comment = self.command == 'POST' and parsed.path == comment_path
        if is_comment:
            state['posts'] += 1
            state['keys'].append(self.headers.get('Idempotency-Key'))
        data = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if self.command == 'POST' else None
        headers = {name: self.headers[name] for name in ('Authorization', 'Content-Type', 'Idempotency-Key') if name in self.headers}
        upstream = urllib.request.Request(api + self.path, data=data, headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(upstream, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = json.load(response)
            if is_comment and state['mode'] == 'lost' and not state['intercepted']:
                assert response.status == 200
                state['intercepted'] = True
                state['committed'] = body
                self.reply(503, {'message': 'response lost after the comment was saved'})
            else:
                self.reply(response.status, body)

    def log_message(self, *_):
        pass


proxy = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
thread = threading.Thread(target=proxy.serve_forever, daemon=True)
thread.start()
proxy_url = f'http://127.0.0.1:{proxy.server_port}'
try:
    # A server without keyed comments is refused before anything is posted.
    old = cli('issue', 'comment', 'IDEMC-1', '-b', 'old server', '--idempotency-key', 'old', url=proxy_url, code=1)
    assert 'upgrade the server' in old.stderr and state['posts'] == 0, (old.stderr, state)

    # The issue's case: the comment is saved but the answer is lost. The
    # retry with the same key returns that comment instead of a second one.
    state.update(mode='lost', posts=0, keys=[], intercepted=False)
    lost = ('issue', 'comment', 'IDEMC-1', '-b', 'lost answer', '--idempotency-key', 'lost', '--json')
    failed = cli(*lost, url=proxy_url, code=1)
    assert '503' in failed.stderr, failed.stderr
    recovered = json.loads(cli(*lost, url=proxy_url).stdout)
    assert recovered['id'] == state['committed']['id'] and recovered['reused'] is True
    assert state['keys'] == ['lost', 'lost']
    assert [c['body'] for c in comments('IDEMC-1')].count('lost answer') == 1
finally:
    proxy.shutdown()
    proxy.server_close()
    thread.join(timeout=5)

print('Comment idempotency: matching/conflicting/per-issue retries, 12 concurrent CLI calls, lost responses and older-server refusal passed')
