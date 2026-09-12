#!/usr/bin/env python3
"""Atomic claim operations through real authenticated HTTP and CLI clients."""
from concurrent.futures import ThreadPoolExecutor
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request

binary, api = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='CLTX')
token = env['LLL_TOKEN']


def request(path, body=None, method=None, auth=token):
    req = urllib.request.Request(api + path,
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={'Authorization': 'Bearer ' + auth, 'Content-Type': 'application/json'})
    try:
        response = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, json.load(response)


def post(collection, body):
    status, result = request('/api/collections/' + collection + '/records', body)
    assert status == 200, result
    return result


def cli(*args, actor=None, endpoint=api):
    settings = dict(env, LLL_URL=endpoint)
    if actor:
        settings.update(LLL_TOKEN=actor['token'], LLL_ME=actor['name'])
    return subprocess.run([binary, *args], env=settings, capture_output=True, text=True, timeout=30)


team = post('teams', {'key': 'CLTX', 'name': 'Claim transactions'})
actors = []
for name in ['claim-alpha', 'claim-beta']:
    password = 'local-claim-fixture-123'
    member = post('members', {'name': name, 'email': name + '@lll.test',
        'password': password, 'passwordConfirm': password})
    status, auth = request('/api/collections/members/auth-with-password',
        {'identity': name + '@lll.test', 'password': password}, auth='')
    assert status == 200
    actors.append(dict(member, token=auth['token']))
alpha, beta = actors
issue = post('issues', {'team': team['id'], 'title': 'Atomic claim verification', 'state': 'todo'})
key = 'CLTX-' + str(issue['number'])
path = '/api/lll/issues/' + issue['id']


def state():
    p = cli('issue', 'view', key, '--json')
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


assert request(path + '/claim', {}, auth='')[0] == 401
assert request(path + '/release', {'claim_id': 'unknown'}, auth='')[0] == 401
assert request(path + '/claim', {'member': beta['id']}, auth=alpha['token'])[0] == 403
assert request(path + '/release', {}, auth=alpha['token'])[0] == 400
assert state()['claim'] is None

# Independent CLI processes compete for the same issue. Every successful
# caller must be the actual holder, and failures must identify that holder.
with ThreadPoolExecutor(max_workers=12) as pool:
    results = list(pool.map(lambda n: (actors[n % 2], cli('issue', 'claim', key, actor=actors[n % 2])), range(24)))
held = state()
holder = held['claim']['member']
assert held['assignee'] == holder
assert any(p.returncode == 0 for _, p in results)
for actor, p in results:
    if actor['id'] == holder:
        assert p.returncode == 0, p.stderr
    else:
        assert p.returncode != 0 and 'already claimed by' in p.stderr, p.stderr
        assert 'lll issue release ' + key in p.stderr
actor = next(a for a in actors if a['id'] == holder)
assert cli('issue', 'claim', key, actor=actor).returncode == 0
assert state()['claim']['id'] == held['claim']['id']
assert state()['claim']['created'] == held['claim']['created']

# A delayed release cannot remove a replacement hold.
assert cli('issue', 'release', key).returncode == 0
assert cli('issue', 'claim', key, actor=beta).returncode == 0
status, rejected = request(path + '/release', {'claim_id': held['claim']['id']})
assert status == 400 and 'claim changed' in rejected['message']
assert state()['claim']['member'] == beta['id'] and state()['assignee'] == beta['id']

# Assignment made by a low-level API client belongs to that edit, not the hold.
assert request('/api/collections/issues/records/' + issue['id'], {'assignee': alpha['id']}, 'PATCH')[0] == 200
p = cli('issue', 'release', key)
assert p.returncode == 0 and 'assignment unchanged' in p.stdout, p.stderr
assert state()['claim'] is None and state()['assignee'] == alpha['id']


class UnsupportedServer(http.server.BaseHTTPRequestHandler):
    writes = []

    def log_message(self, *_):
        pass

    def do_POST(self):
        self.writes.append(self.path)
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"message":"Not Found"}')

    do_PATCH = do_POST
    do_DELETE = do_POST

    def do_GET(self):
        req = urllib.request.Request(api + self.path,
            headers={'Authorization': self.headers.get('Authorization', '')})
        try:
            response = urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.send_response(response.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(response.read())


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), UnsupportedServer)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    proxy = 'http://127.0.0.1:' + str(server.server_port)
    before = state()
    p = cli('issue', 'claim', key, actor=alpha, endpoint=proxy)
    assert p.returncode != 0 and 'update the server' in p.stderr, p.stderr
    assert state() == before
    assert cli('issue', 'claim', key, actor=alpha).returncode == 0
    before = state()
    p = cli('issue', 'release', key, endpoint=proxy)
    assert p.returncode != 0 and 'update the server' in p.stderr, p.stderr
    assert state() == before
    assert UnsupportedServer.writes == [path + '/claim', path + '/release']
finally:
    server.shutdown()
    server.server_close()
    thread.join()

print('Claims: 24 concurrent CLI calls, authenticated actor enforcement, idempotency, stale release, unrelated assignment, and safe refusal on older servers')
