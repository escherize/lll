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
        settings.update(LLL_TOKEN=actor['token'])
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

# LLL-512: the suite's own token does not hold the claim, so it is refused
# and told about --force; the holder releases freely.
p = cli('issue', 'release', key)
assert p.returncode != 0 and 'held by ' + actor['name'] in p.stderr and '--force' in p.stderr, p.stderr
assert state()['claim']['id'] == held['claim']['id']

# A delayed release cannot remove a replacement hold.
assert cli('issue', 'release', key, actor=actor).returncode == 0
assert cli('issue', 'claim', key, actor=beta).returncode == 0
status, rejected = request(path + '/release', {'claim_id': held['claim']['id']})
assert status == 400 and 'claim changed' in rejected['message']
assert state()['claim']['member'] == beta['id'] and state()['assignee'] == beta['id']

# Assignment made by a low-level API client belongs to that edit, not the hold.
assert request('/api/collections/issues/records/' + issue['id'], {'assignee': alpha['id']}, 'PATCH')[0] == 200
p = cli('issue', 'release', key, actor=beta)
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

# Assignment edits commit all accompanying fields with the claim policy.
held = state()['claim']
before = state()
p = cli('issue', 'update', key, '--assignee', beta['name'], '--title', 'must not commit')
assert p.returncode != 0 and 'is claimed by' in p.stderr and 'lll issue release ' + key in p.stderr
assert state() == before
p = cli('issue', 'update', key, '--assignee', alpha['name'], '--title', 'same holder edit', '--priority', 'high')
assert p.returncode == 0, p.stderr
assert state()['claim']['id'] == held['id'] and state()['title'] == 'same holder edit' and state()['priority'] == 2

# Native field validation must roll back the deletion as well as the edit.
before = state()
status, error = request(path + '/assignment', {'claim_id': held['id'], 'fields': {'assignee': '', 'title': ''}})
assert status == 400 and 'title' in error['data'], error
assert state() == before
for body in [{}, {'fields': {'assignee': ''}}, {'claim_id': '', 'fields': {'assignee': '', 'id': 'forged'}}]:
    assert request(path + '/assignment', body)[0] == 400
assert request(path + '/assignment', {'claim_id': held['id'], 'fields': {'assignee': ''}}, auth='')[0] == 401
assert state() == before
p = cli('issue', 'update', key, '--assignee', 'none', '--title', 'released with edit', '--description', 'café transaction')
assert p.returncode == 0 and "released claim-alpha's claim" in p.stdout, p.stderr
assert state()['claim'] is None and state()['assignee'] == '' and state()['title'] == 'released with edit'
assert state()['description'] == 'café transaction'
for assignee in [alpha['name'], beta['name'], 'none']:
    p = cli('issue', 'update', key, '--assignee', assignee)
    assert p.returncode == 0, p.stderr
    assert state()['claim'] is None
    assert state()['assignee'] == ('' if assignee == 'none' else next(a['id'] for a in actors if a['name'] == assignee))


class DelayedAssignment(UnsupportedServer):
    paused = threading.Event()
    resume = threading.Event()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        if self.path.endswith('/assignment'):
            self.paused.set()
            if not self.resume.wait(15):
                self.send_error(500)
                return
        req = urllib.request.Request(api + self.path, data=body,
            headers={'Authorization': self.headers.get('Authorization', ''), 'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.send_response(response.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(response.read())


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), DelayedAssignment)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    proxy = 'http://127.0.0.1:' + str(server.server_port)
    for assignee in ['none', alpha['name']]:
        DelayedAssignment.paused.clear()
        DelayedAssignment.resume.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(cli, 'issue', 'update', key, '--assignee', assignee,
                '--title', 'stale title must not commit', endpoint=proxy)
            assert DelayedAssignment.paused.wait(10), 'update did not reach transaction boundary'
            assert cli('issue', 'claim', key, actor=beta).returncode == 0
            before = state()
            DelayedAssignment.resume.set()
            p = pending.result(timeout=25)
        assert p.returncode != 0 and 'claim changed' in p.stderr, p.stderr
        assert state() == before
        assert cli('issue', 'release', key, actor=beta).returncode == 0
finally:
    DelayedAssignment.resume.set()
    server.shutdown()
    server.server_close()
    thread.join()

# Unsupported assignment routes must not trigger either legacy write.
UnsupportedServer.writes = []
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), UnsupportedServer)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    before = state()
    p = cli('issue', 'update', key, '--assignee', 'none', endpoint='http://127.0.0.1:' + str(server.server_port))
    assert p.returncode != 0 and 'update the server' in p.stderr, p.stderr
    assert UnsupportedServer.writes == [path + '/assignment'] and state() == before
finally:
    server.shutdown()
    server.server_close()
    thread.join()

print('Assignment: whole-edit rollback, none/same/different holder, invalid fields, delayed CLI clear/reassignment, and older-server refusal')

# LLL-512: a claim leaves only through /release. The collection's DELETE is
# superuser-only, for the holder as much as anyone, so the holder check on the
# route cannot be walked around.
assert cli('issue', 'claim', key, actor=alpha).returncode == 0
held = state()['claim']
comments = len(state()['comments'])
for who in [alpha, beta]:
    status, refused = request('/api/collections/claims/records/' + held['id'], method='DELETE', auth=who['token'])
    assert status == 403, (status, refused)
assert state()['claim']['id'] == held['id']

# A non-holder is refused through the route too, and changes nothing.
status, refused = request(path + '/release', {'claim_id': held['id']}, auth=beta['token'])
assert status == 400 and 'needs force' in refused['message'], refused
p = cli('issue', 'release', key, actor=beta)
assert p.returncode != 0 and 'lll issue release ' + key + ' --force' in p.stderr, p.stderr
p = cli('issue', 'release', key, '-b', 'no force', actor=beta)
assert p.returncode != 0 and 'add --force' in p.stderr, p.stderr
assert state()['claim']['id'] == held['id'] and len(state()['comments']) == comments

# Forced, it goes through and the issue says who took whose claim and why.
p = cli('issue', 'release', key, '--force', '-b', 'alpha went quiet', actor=beta)
assert p.returncode == 0 and 'forced, and commented' in p.stdout, p.stderr
after = state()
assert after['claim'] is None and len(after['comments']) == comments + 1
note = after['comments'][-1]
assert note['body'] == "claim-beta force-released claim-alpha's claim.\n\nReason: alpha went quiet", note
assert note['author'] == beta['id'], note

# The holder's own release, forced or not, leaves no comment.
assert cli('issue', 'claim', key, actor=alpha).returncode == 0
p = cli('issue', 'release', key, '--force', actor=alpha)
assert p.returncode == 0 and 'forced' not in p.stdout, p.stdout
assert state()['claim'] is None and len(state()['comments']) == comments + 1

print('Release: collection DELETE refused for holder and non-holder, non-holder refused without force, forced release comments with the reason, holder release silent')
