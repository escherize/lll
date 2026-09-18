#!/usr/bin/env python3
"""LLL-438: keyed creates survive retries without another issue or mutation."""
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
env = dict(os.environ, LLL_URL=api, LLL_TEAM='IDEMA')


def request(path, payload=None, *, method=None, token=None, key=None, raw=None, content='application/json'):
    headers = {'Authorization': 'Bearer ' + (env['LLL_TOKEN'] if token is None else token)}
    data = raw if raw is not None else (None if payload is None else json.dumps(payload).encode())
    if data is not None:
        headers['Content-Type'] = content
    if key is not None:
        headers['Idempotency-Key'] = key
    req = urllib.request.Request(api + path, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def post(collection, payload, **options):
    status, body = request('/api/collections/' + collection + '/records', payload, **options)
    assert status == 200, (status, body)
    return body


def cli(*args, url=api, success=True, **overrides):
    result = subprocess.run([binary, *args], env=dict(env, LLL_URL=url, **overrides),
                            text=True, capture_output=True, timeout=30)
    assert (result.returncode == 0) == success, (result.args, result.returncode, result.stdout, result.stderr)
    return result


a = post('teams', {'key': 'IDEMA', 'name': 'Idempotency A'})
b = post('teams', {'key': 'IDEMB', 'name': 'Idempotency B'})
assert request('/api/lll/issues/idempotency')[1] == {'supported': True}
assert request('/api/lll/issues/idempotency', token='')[0] == 401

# Same key and payload return the same expanded committed issue, in either
# output mode. A repeat leaves updated and the next issue number untouched.
args = ('issue', 'create', '-t', 'Sequential retry', '-d', 'Stable body', '--idempotency-key', 'sequential')
first = json.loads(cli(*args, '--json').stdout)
second = json.loads(cli(*args, '--json').stdout)
assert second['id'] == first['id'] and second['number'] == first['number']
assert second['updated'] == first['updated'] and second['reused'] is True
assert second['expand']['team']['key'] == 'IDEMA'
assert second['expand']['creator']['id'] == first['creator']
assert cli(*args).stdout.startswith(f'Reused IDEMA-{first["number"]}:')
conflict = cli('issue', 'create', '-t', 'Changed body', '--idempotency-key', 'sequential', success=False)
assert '409' in conflict.stderr and 'different creation payload' in conflict.stderr
other = json.loads(cli(*args, '--json', LLL_TEAM='IDEMB').stdout)
assert other['id'] != first['id'] and other['number'] == 1

# Canonical JSON is insensitive to object ordering and a forged creator is
# replaced by the authenticated account before fingerprinting.
path = '/api/collections/issues/records'
payload = {'team': a['id'], 'title': 'Canonical JSON', 'state': 'todo', 'origin': {'host': 'fixture', 'tool': 'probe'}}
status, canonical = request(path, dict(payload, creator='forged'), key='canonical')
assert status == 200
reverse = dict(reversed(list(payload.items())))
reverse['origin'] = dict(reversed(list(payload['origin'].items())))
status, replay = request(path, reverse, key='canonical')
assert status == 200 and replay['id'] == canonical['id'] and replay['reused']
assert replay['creator'] == first['creator']

# Creation metadata stays immutable even through direct API patches. The
# replay returns the current issue without applying the old creation again.
status, edited = request(path + '/' + first['id'], {'title': 'Edited after creation',
    'idempotency_key': 'forged-key', 'idempotency_fingerprint': 'forged'}, method='PATCH')
assert status == 200
after_edit = json.loads(cli(*args, '--json').stdout)
assert after_edit['id'] == first['id'] and after_edit['title'] == 'Edited after creation'
assert after_edit['updated'] == edited['updated'] and after_edit['reused']

# Concurrent CLI retries exercise the capability check, JSON transport,
# transaction and issue-number allocator together.
race_args = ('issue', 'create', '-t', 'Concurrent retry', '--idempotency-key', 'concurrent', '--json')
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    results = list(pool.map(lambda _: json.loads(cli(*race_args).stdout), range(24)))
assert len({record['id'] for record in results}) == 1
assert len({record['number'] for record in results}) == 1
assert sum(not record.get('reused', False) for record in results) == 1
next_issue = json.loads(cli('issue', 'create', '-t', 'Unkeyed create', '--json').stdout)
assert next_issue['number'] == results[0]['number'] + 1
another = json.loads(cli('issue', 'create', '-t', 'Unkeyed create', '--json').stdout)
assert another['id'] != next_issue['id']

# Validation failure must not reserve the key, and non-JSON requests cannot
# claim a guarantee based on an incomplete fingerprint of uploaded data.
assert request(path, {'team': a['id'], 'title': '', 'state': 'todo'}, key='validation')[0] == 400
status, validated = request(path, {'team': a['id'], 'title': 'Validated retry', 'state': 'todo'}, key='validation')
assert status == 200, (status, validated)
assert request(path, raw=b'title=not-json', key='multipart', content='application/x-www-form-urlencoded')[0] == 400
assert request(path, {'team': a['id'], 'title': 'Empty key'}, key='')[0] == 400
for empty in ('', '   '):
    result = cli('issue', 'create', '-t', 'Empty key', '--idempotency-key', empty,
                 url='http://127.0.0.1:1', success=False)
    assert '--idempotency-key must not be empty' in result.stderr

admin = request('/api/collections/_superusers/auth-with-password',
    {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']}, token='')[1]['token']
member = post('members', {'name': 'idempotency-renew', 'email': 'idempotency-renew@lll.test',
    'password': 'idempotency-pass-123', 'passwordConfirm': 'idempotency-pass-123'}, token=admin)
member_token = request('/api/collections/members/impersonate/' + member['id'], {'duration': 3600}, token=admin)[1]['token']

state = {'mode': 'old', 'posts': 0, 'keys': [], 'committed': None, 'intercepted': False}


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
        if state['mode'] == 'old' and parsed.path == '/api/lll/issues/idempotency':
            self.reply(404, {'message': 'not supported'})
            return
        is_create = self.command == 'POST' and parsed.path == path
        if is_create:
            state['posts'] += 1
            state['keys'].append(self.headers.get('Idempotency-Key'))
            if state['mode'] == 'renew' and not state['intercepted']:
                state['intercepted'] = True
                status, _ = request('/api/collections/members/records/' + member['id'],
                    {'password': 'rotated-idempotency-pass-123', 'passwordConfirm': 'rotated-idempotency-pass-123'},
                    method='PATCH', token=admin)
                assert status == 200
                self.reply(401, {'message': 'credential revoked before create'})
                return
        data = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if self.command == 'POST' else None
        headers = {name: self.headers[name] for name in ('Authorization', 'Content-Type', 'Idempotency-Key') if name in self.headers}
        upstream = urllib.request.Request(api + self.path, data=data, headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(upstream, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = json.load(response)
            if is_create and state['mode'] == 'lost' and not state['intercepted']:
                assert response.status == 200
                state['intercepted'] = True
                state['committed'] = body
                self.reply(503, {'message': 'response lost after committed create'})
            else:
                self.reply(response.status, body)

    def log_message(self, *_):
        pass


proxy = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
thread = threading.Thread(target=proxy.serve_forever, daemon=True)
thread.start()
proxy_url = f'http://127.0.0.1:{proxy.server_port}'
try:
    old = cli('issue', 'create', '-t', 'Old server', '--idempotency-key', 'old', url=proxy_url, success=False)
    assert 'upgrade the server' in old.stderr and state['posts'] == 0

    state.update(mode='lost', posts=0, keys=[], intercepted=False)
    lost_args = ('issue', 'create', '-t', 'Lost response', '--idempotency-key', 'lost-response', '--json')
    lost = cli(*lost_args, url=proxy_url, success=False)
    assert '503' in lost.stderr
    recovered = json.loads(cli(*lost_args, url=proxy_url).stdout)
    assert recovered['id'] == state['committed']['id'] and recovered['reused']
    assert state['keys'] == ['lost-response', 'lost-response']

    state.update(mode='renew', posts=0, keys=[], intercepted=False)
    renewed = json.loads(cli('issue', 'create', '-t', 'Renewed keyed create',
        '--idempotency-key', 'renewed', '--json', url=proxy_url, LLL_TOKEN=member_token,
        LLL_REMINT='1', LLL_REMINT_MEMBER=member['id']).stdout)
    assert renewed['creator'] == member['id'] and state['keys'] == ['renewed', 'renewed']
finally:
    proxy.shutdown()
    proxy.server_close()
    thread.join(timeout=5)

print('Issue idempotency: matching/conflicting/team-scoped retries, 24 concurrent CLI calls, canonical JSON, immutable metadata, lost responses, renewal and older-server refusal passed')
