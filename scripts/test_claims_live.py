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

# LLL-515: the raw collection endpoint cannot bypass the identity check or
# create a hold without the claim route's transactional assignment write.
for member in (alpha, beta):
    status, rejected = request('/api/collections/claims/records',
        {'issue': issue['id'], 'member': member['id']}, auth=alpha['token'])
    assert status == 403, (status, rejected)
    unchanged = state()
    assert unchanged['claim'] is None and unchanged['assignee'] == ''
print('Claims: direct member-token creation refused for self and another holder, with no claim or assignment side effects')

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
        assert 'lll issue release ' + key + ' --force' in p.stderr, p.stderr
actor = next(a for a in actors if a['id'] == holder)
assert cli('issue', 'claim', key, actor=actor).returncode == 0
assert state()['claim']['id'] == held['claim']['id']
assert state()['claim']['claimed'] == held['claim']['claimed']

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

# LLL-516: a native PATCH cannot move a claimed issue's assignee away from the
# holder unless the holder sends it. PATCH has no force and writes no comment,
# so another member and a superuser are refused, and nothing changes.
su = os.environ['LLL_TEST_SUPERUSER_TOKEN']
for auth in [token, alpha['token'], su]:
    for assignee in ['', alpha['id']]:
        status, refused = request('/api/collections/issues/records/' + issue['id'], {'assignee': assignee}, 'PATCH', auth=auth)
        assert status == 400 and 'held by claim-beta' in refused['message'] and 'force' in refused['message'], (status, refused)
assert state()['claim']['member'] == beta['id'] and state()['assignee'] == beta['id']
# Assigning the holder, or editing another field, is not a move.
assert request('/api/collections/issues/records/' + issue['id'], {'assignee': beta['id'], 'priority': 3}, 'PATCH')[0] == 200

# Assignment the holder makes with a low-level API client belongs to that
# edit, not the hold.
assert request('/api/collections/issues/records/' + issue['id'], {'assignee': alpha['id']}, 'PATCH', auth=beta['token'])[0] == 200
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

# Native field validation must roll back the deletion as well as the edit. The
# holder sends it, so the release rule (LLL-516) lets it reach validation.
before = state()
status, error = request(path + '/assignment', {'claim_id': held['id'], 'fields': {'assignee': '', 'title': ''}}, auth=alpha['token'])
assert status == 400 and 'title' in error['data'], error
assert state() == before
for body in [{}, {'fields': {'assignee': ''}}, {'claim_id': '', 'fields': {'assignee': '', 'id': 'forged'}}]:
    assert request(path + '/assignment', body)[0] == 400
assert request(path + '/assignment', {'claim_id': held['id'], 'fields': {'assignee': ''}}, auth='')[0] == 401
assert state() == before
# LLL-516: clearing the assignee releases the claim, so a non-holder (the
# suite's own token, or a superuser) is refused without force, naming the
# holder and the CLI's --force, and the whole edit stays uncommitted.
p = cli('issue', 'update', key, '--assignee', 'none', '--title', 'must not commit')
assert p.returncode != 0 and 'held by claim-alpha' in p.stderr and 'needs force' in p.stderr, p.stderr
assert 'lll issue update ' + key + ' --assignee none --force' in p.stderr, p.stderr
status, refused = request(path + '/assignment', {'claim_id': held['id'], 'fields': {'assignee': ''}}, auth=su)
assert status == 400 and 'needs force' in refused['message'], refused
p = cli('issue', 'update', key, '--assignee', 'none', '-b', 'no force', actor=beta)
assert p.returncode != 0 and 'add --force' in p.stderr, p.stderr
p = cli('issue', 'update', key, '--title', 'x', '--force')
assert p.returncode != 0 and 'goes with --assignee none' in p.stderr, p.stderr
assert state() == before
# The holder clears freely, and it is not a forced release.
p = cli('issue', 'update', key, '--assignee', 'none', '--title', 'released with edit', '--description', 'café transaction', actor=alpha)
assert p.returncode == 0 and "released claim-alpha's claim)" in p.stdout and 'forced' not in p.stdout, (p.stdout, p.stderr)
assert len(state()['comments']) == len(before['comments'])
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

# LLL-516: forced, a non-holder's clear goes through and leaves the comment a
# forced release leaves, with the reason; a superuser's has no author.
assert cli('issue', 'claim', key, actor=alpha).returncode == 0
comments = len(state()['comments'])
p = cli('issue', 'update', key, '--assignee', 'none', '--force', '-b', 'alpha went quiet', actor=beta)
assert p.returncode == 0 and "released claim-alpha's claim; forced, and commented" in p.stdout, (p.stdout, p.stderr)
after = state()
assert after['claim'] is None and after['assignee'] == '' and len(after['comments']) == comments + 1
note = after['comments'][-1]
assert note['body'] == "claim-beta force-released claim-alpha's claim.\n\nReason: alpha went quiet" and note['author'] == beta['id'], note
assert cli('issue', 'claim', key, actor=alpha).returncode == 0
held = state()['claim']
status, outcome = request(path + '/assignment', {'claim_id': held['id'], 'fields': {'assignee': ''}, 'force': True}, auth=su)
assert status == 200 and outcome['forced'] and outcome['cleared_assignee'], outcome
note = state()['comments'][-1]
assert note['author'] == '' and note['body'] == "An administrator force-released claim-alpha's claim.", note
assert state()['claim'] is None and len(state()['comments']) == comments + 2

print('Assignment: whole-edit rollback, none/same/different holder, invalid fields, delayed CLI clear/reassignment, older-server refusal, and a non-holder clear refused without force and commented with it (LLL-516)')

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

# A superuser token names no member, so it is never the holder: it needs
# force like anyone else, and its comment has no author.
su = os.environ['LLL_TEST_SUPERUSER_TOKEN']
assert cli('issue', 'claim', key, actor=alpha).returncode == 0
held = state()['claim']
status, refused = request(path + '/release', {'claim_id': held['id']}, auth=su)
assert status == 400 and 'needs force' in refused['message'], refused
assert state()['claim']['id'] == held['id']
status, outcome = request(path + '/release', {'claim_id': held['id'], 'force': True}, auth=su)
assert status == 200 and outcome['forced'], outcome
note = state()['comments'][-1]
assert note['author'] == '' and note['body'].startswith("An administrator force-released claim-alpha's claim."), note
assert state()['claim'] is None and len(state()['comments']) == comments + 2

print('Release: superuser needs force and comments without an author; collection DELETE refused for holder and non-holder, non-holder refused without force, forced release comments with the reason, holder release silent')

# LLL-521: an agent label is rendered into comments (markdown), so the server
# refuses any label outside [A-Za-z0-9._-]{0,64} at every route that takes one,
# and the stored fields carry the same pattern. A refusal changes nothing.
rule = "agent label must be at most 64 characters from A-Z, a-z, 0-9, '.', '_' and '-'"
bad_labels = ["wt-a)'s claim. [x](https://evil)", 'a' * 65, 'wt a', 'wt\nb']
assert cli('issue', 'claim', key, actor=alpha).returncode == 0
held = state()['claim']
claim_record = '/api/collections/claims/records/' + held['id']
held_updated = request(claim_record, auth=alpha['token'])[1]['updated']
comments = len(state()['comments'])
for bad in bad_labels:
    for route, body in [('/claim', {}), ('/renew', {'claim_id': held['id']}), ('/release', {'claim_id': held['id']})]:
        status, refused = request(path + route, dict(body, agent=bad), auth=alpha['token'])
        assert status == 400 and refused['message'].rstrip('.').lower() == rule.lower(), (route, bad, status, refused)
    status, refused = request('/api/collections/comments/records',
                              {'issue': issue['id'], 'author': alpha['id'], 'body': 'x', 'agent': bad}, auth=alpha['token'])
    assert status == 400 and 'agent' in refused.get('data', {}), (bad, status, refused)
after = state()
assert after['claim']['id'] == held['id'], after['claim']
assert request(claim_record, auth=alpha['token'])[1]['updated'] == held_updated, 'a refused renew moved the clock'
assert len(after['comments']) == comments
for good in ['wt-a', 'A.b_c-9', 'a' * 64]:
    status, _ = request(path + '/renew', {'claim_id': held['id'], 'agent': good}, auth=alpha['token'])
    assert status == 200, good
# The CLI refuses before any request: an unreachable endpoint still yields the
# label error, not a connection error.
dead = 'http://127.0.0.1:1'
for argv in [['issue', 'claim', key], ['issue', 'claim', key, '--renew'], ['issue', 'release', key],
             ['issue', 'next', '--claim'], ['issue', 'comment', key, '-b', 'x']]:
    p = cli(*argv, '--agent', bad_labels[0], actor=alpha, endpoint=dead)
    assert p.returncode != 0 and 'invalid agent label' in p.stderr and '127.0.0.1:1' not in p.stderr, (argv, p.stderr)
p = subprocess.run([binary, 'issue', 'claim', key], env=dict(env, LLL_AGENT='bad label', LLL_URL=dead, LLL_TOKEN=alpha['token']),
                   capture_output=True, text=True, timeout=30)
assert p.returncode != 0 and 'from --agent or LLL_AGENT' in p.stderr, p.stderr
assert cli('issue', 'release', key, actor=alpha).returncode == 0

print('Agent labels: claim, renew, release and comment create refuse a malformed label with no side effect; the CLI refuses before sending')
