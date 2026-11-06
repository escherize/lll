#!/usr/bin/env python3
"""Machine bot credentials keep the existing ownership and retry rules."""
import http.server
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
assert urllib.parse.urlsplit(api).hostname == '127.0.0.1', 'requires an isolated loopback board'
owner_token = os.environ['LLL_TOKEN']
env = dict(os.environ, LLL_URL=api, LLL_TEAM='MISSING-JSON-CONTEXT')
jwt = re.compile(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')


def cli(*args, extra=None, expected=0):
    result = subprocess.run([binary, *args], env=env | (extra or {}),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == expected, f'{args[:3]} returned {result.returncode}, expected {expected}'
    return result


def call(path, body=None, token=None, method=None):
    request = urllib.request.Request(api + path, data=None if body is None else json.dumps(body).encode(),
        method=method, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (token or owner_token)})
    try:
        response = urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


def members():
    code, page = call('/api/collections/members/records?perPage=500')
    assert code == 200
    return {row['name']: row for row in page['items']}


def credentials(result, name, team=''):
    packet = json.loads(result.stdout)
    assert set(packet) == {'name', 'url', 'token', 'team'}, 'unexpected credential fields'
    assert (packet['name'], packet['url'], packet['team']) == (name, api, team)
    assert packet['token'] and result.stdout.endswith('\n')
    assert not result.stderr, 'credential output carried a notice'
    code, _ = call('/api/collections/members/auth-refresh', {}, packet['token'])
    assert code == 200, 'printed credential does not authenticate'
    return packet


# No configured/visible team is needed. A known-invalid configured context
# must not be mistaken for an access restriction or trigger attachment.
first = credentials(cli('bot', 'create', 'bot-json-owner', '--json'), 'bot-json-owner')
credentials(cli('bot', 'bot-json-bare', '--json'), 'bot-json-bare')
created = members()['bot-json-owner']
assert created['owner'] and created['kind'] == 'bot'
owner_id = created['owner']
cli('bot', 'create', 'bot-json-owner', '--json', expected=4)
assert call('/api/collections/members/auth-refresh', {}, first['token'])[0] == 200

code, team = call('/api/collections/teams/records', {'key': 'JSONBOT', 'name': 'Bot JSON context'})
assert code == 200
context = credentials(cli('bot', 'create', 'bot-json-context', '--json', '--team', 'JSONBOT'),
                      'bot-json-context', 'JSONBOT')
context_row = members()['bot-json-context']
assert context_row['scope'] == 'all' and context_row['owner'] == owner_id, 'team context changed grants'
worker = credentials(cli('bot', 'create', 'bot-json-worker', '--json', extra={'LLL_TOKEN': first['token']}),
                     'bot-json-worker')
worker_row = members()['bot-json-worker']
assert worker_row['owner'] == owner_id and worker_row['created_by'] == created['id']

before = members()
failed = cli('bot', 'create', 'bot-json-invisible', '--json', '--team', 'NOT-VISIBLE', expected=1)
assert not failed.stdout and set(members()) == set(before)

# Invalid format combinations fail before even an authentication/discovery
# request. A request-counting server makes this stronger than an error code.
class RejectIO(http.server.BaseHTTPRequestHandler):
    calls = 0
    def do_GET(self):
        type(self).calls += 1
        self.send_error(500)
    do_POST = do_GET
    def log_message(self, *args):
        pass


guard = http.server.ThreadingHTTPServer(('127.0.0.1', 0), RejectIO)
guard.daemon_threads = True
thread = threading.Thread(target=guard.serve_forever, daemon=True)
thread.start()
try:
    for verb in ('create', 'rotate'):
        failure = cli('bot', verb, 'bot-json-bad-format', '--json', '--env', expected=2,
                      extra={'LLL_URL': f'http://127.0.0.1:{guard.server_port}'})
        assert not failure.stdout
    assert RejectIO.calls == 0, 'invalid format reached the server'
finally:
    guard.shutdown()
    guard.server_close()
    thread.join(timeout=5)
before = set(members())
cli('bot', 'create', 'bot-json-empty-context', '--json', '--team', '', expected=2)
assert set(members()) == before, 'empty context wrote a member'

# Output format changes no authority. Another person and the bot itself
# cannot rotate it; the human owner can, and the previous token retires.
code, outsider = call('/api/collections/members/records', {'name': 'json-outsider',
    'email': 'json-outsider@example.invalid', 'password': 'isolated-password', 'passwordConfirm': 'isolated-password'})
assert code == 200
code, login = call('/api/collections/members/auth-with-password',
                  {'identity': 'json-outsider@example.invalid', 'password': 'isolated-password'})
assert code == 200
for token in (login['token'], first['token']):
    refused = cli('bot', 'rotate', 'bot-json-owner', '--json', extra={'LLL_TOKEN': token}, expected=4)
    assert not refused.stdout and not jwt.search(refused.stderr)
assert call('/api/collections/members/auth-refresh', {}, first['token'])[0] == 200
rotated = credentials(cli('bot', 'rotate', 'bot-json-owner', '--json'), 'bot-json-owner')
assert rotated['token'] != first['token']
assert call('/api/collections/members/auth-refresh', {}, first['token'])[0] == 401

# Preserve the existing formats as actual native output, not a shell eval.
exports = cli('bot', 'create', 'bot-json-env-control', '--env')
assert not exports.stderr
parsed = {}
for line in exports.stdout.splitlines():
    parts = shlex.split(line)
    assert len(parts) == 2 and parts[0] == 'export'
    key, value = parts[1].split('=', 1)
    parsed[key] = value
assert set(parsed) == {'LLL_URL', 'LLL_TOKEN'}
assert call('/api/collections/members/auth-refresh', {}, parsed['LLL_TOKEN'])[0] == 200
prompt = cli('bot', 'create', 'bot-json-prompt-control', '--team', 'JSONBOT')
assert 'paste this into the agent:' in prompt.stdout and 'lll attach --key JSONBOT' in prompt.stdout
assert not prompt.stderr

# Lost one-time credentials remain an error with a same-format recovery
# command, with no JSON/token copied to stderr.
for verb, name in [('rotate', 'bot-json-owner'), ('create', 'bot-json-lost-create')]:
    process = subprocess.Popen([binary, 'bot', verb, name, '--json'], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.stdout.close()
    process.stdout = None
    _, error = process.communicate(timeout=30)
    error = error.decode()
    assert process.returncode != 0 and 'not written anywhere' in error, f'output-loss exit={process.returncode}, stderr_empty={not error}'
    assert f'lll bot rotate {name} --json' in error and not jwt.search(error)
    assert name in members(), 'committed bot was hidden after output loss'
    credentials(cli('bot', 'rotate', name, '--json'), name)

# A committed create followed by a refused mint must not look like no write
# happened, print a partial credential, or retry creation automatically.
class FailMint(http.server.BaseHTTPRequestHandler):
    creates = 0
    mints = 0
    def forward(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if self.command == 'POST' else None
        if self.path == '/api/lll/bots/rotate' and self.command == 'POST':
            type(self).mints += 1
            self.send_response(503)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"message":"synthetic mint unavailable"}')
            return
        if self.command == 'POST' and self.path.startswith('/api/collections/members/records'):
            type(self).creates += 1
        request = urllib.request.Request(api + self.path, data=body, method=self.command,
            headers={'Content-Type': 'application/json', 'Authorization': self.headers.get('Authorization', '')})
        try:
            response = urllib.request.urlopen(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            data = response.read()
            self.send_response(response.status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(data)
    do_GET = forward
    do_POST = forward
    def log_message(self, *args):
        pass


proxy = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FailMint)
proxy.daemon_threads = True
thread = threading.Thread(target=proxy.serve_forever, daemon=True)
thread.start()
try:
    failure = cli('bot', 'create', 'bot-json-mint-failed', '--json', expected=1,
                  extra={'LLL_URL': f'http://127.0.0.1:{proxy.server_port}'})
    assert not failure.stdout and not jwt.search(failure.stderr)
    assert 'was created' in failure.stderr and 'lll bot rotate bot-json-mint-failed --json' in failure.stderr
    assert 'bot-json-mint-failed' in members()
    assert FailMint.creates == 1 and FailMint.mints == 1, 'failed mint retried a write'
finally:
    proxy.shutdown()
    proxy.server_close()
    thread.join(timeout=5)
credentials(cli('bot', 'rotate', 'bot-json-mint-failed', '--json'), 'bot-json-mint-failed')
print('Bot JSON: exact packet, optional context, owner/creator bounds, invalid no-I/O formats, create refusal, rotation, legacy formats and lost/failed-token recovery passed')
