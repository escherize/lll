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
        data = response.read()  # a 204 delete has no body
        return response.code, json.loads(data) if data else {}


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
p = cli('issue', 'update', key, '--assignee', 'none', '--reason', 'no force', actor=beta)
assert p.returncode != 0 and 'add --force' in p.stderr, p.stderr
# LLL-646: -b is the description on update now, so the old forced-clear
# spelling is refused naming --reason rather than overwriting the description.
p = cli('issue', 'update', key, '--assignee', 'none', '--force', '-b', 'alpha went quiet', actor=beta)
assert p.returncode != 0 and '--reason' in p.stderr and 'description' in p.stderr, p.stderr
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
p = cli('issue', 'update', key, '--assignee', 'none', '--force', '--reason', 'alpha went quiet', actor=beta)
assert p.returncode == 0 and "released claim-alpha's claim; forced, and commented" in p.stdout, (p.stdout, p.stderr)
after = state()
assert after['claim'] is None and after['assignee'] == '' and len(after['comments']) == comments + 1
note = after['comments'][-1]
assert note['body'] == "claim-beta force-released claim-alpha's claim.\n\nReason: alpha went quiet" and note['author'] == beta['id'], note
assert note.get('author_kind', '') == '', note
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
for argv in [['issue', 'claim', key], ['issue', 'claim', key, '--renew'], ['issue', 'release', key], ['issue', 'close', key],
             ['issue', 'next', '--claim'], ['issue', 'comment', key, '-b', 'x']]:
    p = cli(*argv, '--agent', bad_labels[0], actor=alpha, endpoint=dead)
    assert p.returncode != 0 and 'invalid agent label' in p.stderr and '127.0.0.1:1' not in p.stderr, (argv, p.stderr)
p = subprocess.run([binary, 'issue', 'claim', key], env=dict(env, LLL_AGENT='bad label', LLL_URL=dead, LLL_TOKEN=alpha['token']),
                   capture_output=True, text=True, timeout=30)
assert p.returncode != 0 and 'from --agent or LLL_AGENT' in p.stderr, p.stderr
assert cli('issue', 'release', key, actor=alpha).returncode == 0

print('Agent labels: claim, renew, release and comment create refuse a malformed label with no side effect; the CLI refuses before sending')


def set_state(value):
    status, record = request('/api/collections/issues/records/' + issue['id'], {'state': value}, 'PATCH', auth=su)
    assert status == 200, record


# D3 (LLL-640): close releases the closer's claim and keeps the assignee.
# Closing an issue another member holds is the release rule's case.
set_state('todo')
assert cli('issue', 'claim', key, actor=alpha).returncode == 0
before = state()
p = cli('issue', 'close', key, actor=beta)
assert p.returncode != 0 and 'needs force' in p.stderr and "'lll issue close " + key + " --force --reason" in p.stderr, p.stderr
p = cli('issue', 'close', key, '--keep-claim', '--force', actor=beta)
assert p.returncode != 0 and 'only the holder keeps a claim' in p.stderr, p.stderr
p = cli('issue', 'close', key, '--reason', 'no force', actor=beta)
assert p.returncode != 0 and 'add --force' in p.stderr, p.stderr
assert state() == before
p = cli('issue', 'close', key, actor=alpha)
assert p.returncode == 0 and "Released claim-alpha's claim; assignee unchanged." in p.stdout, (p.stdout, p.stderr)
after = state()
assert after['state'] == 'done' and after['claim'] is None and after['assignee'] == alpha['id'], after
assert len(after['comments']) == len(before['comments'])
set_state('todo')
assert cli('issue', 'claim', key, actor=alpha).returncode == 0
p = cli('issue', 'close', key, '--force', '--reason', 'shipped by beta', actor=beta)
assert p.returncode == 0 and 'forced, and commented' in p.stdout, (p.stdout, p.stderr)
note = state()['comments'][-1]
assert note['body'] == "claim-beta force-released claim-alpha's claim.\n\nReason: shipped by beta", note
assert note['author'] == beta['id'] and note.get('author_kind', '') == '', note
assert state()['claim'] is None and state()['state'] == 'done'
print('Close: the holder releases and keeps the assignee; a non-holder is refused without force, cannot keep the claim, and a forced close comments with the reason')

# LLL-654: author_kind is the server's word. No request sets it, so neither a
# member nor a superuser can make a comment, or a server-shaped sentence,
# read as the server's. The forced-release comment carries the releaser's
# reason, so it is the releaser's (checked above) and reads under its name.
for who in [alpha['token'], su]:
    for body in ['forged', "claim-beta force-released claim-alpha's claim."]:
        status, refused = request('/api/collections/comments/records',
                                  {'issue': issue['id'], 'body': body, 'author_kind': 'system'}, auth=who)
        assert status == 400, (status, refused)
plain = post('comments', {'issue': issue['id'], 'body': "claim-beta force-released claim-alpha's claim."})
assert plain['author_kind'] == '', plain
for who in [alpha['token'], su]:
    status, refused = request('/api/collections/comments/records/' + plain['id'], {'author_kind': 'system'}, 'PATCH', auth=who)
    assert status == 400, (status, refused)
assert all(c.get('author_kind', '') == '' for c in state()['comments']), state()['comments']
# A member's comment is that member's: it cannot be posted authorless or in
# another member's name, so neither an expiry-shaped note nor a forced-release
# record can be planted, and the author cannot be moved afterwards.
for body in [{'body': 'Claim released automatically: claim-alpha had held it for 25 hours.'},
             {'body': "claim-beta force-released claim-alpha's claim.", 'author': beta['id']},
             {'body': 'authorless', 'author': ''}]:
    status, made = request('/api/collections/comments/records', dict(body, issue=issue['id']), auth=alpha['token'])
    assert status == 200 and made['author'] == alpha['id'] and made['author_kind'] == '', (status, made)
status, refused = request('/api/collections/comments/records/' + made['id'], {'author': beta['id']}, 'PATCH', auth=alpha['token'])
assert status == 400 and "author cannot be changed" in refused['message'], refused
# Only a comment's author edits or deletes it: alpha can neither rewrite nor
# remove beta's forced-release record (note) or an ordinary beta comment,
# through the API or the CLI, nor touch an authorless one. Beta can.
status, theirs = request('/api/collections/comments/records', {'issue': issue['id'], 'body': 'beta said this'}, auth=beta['token'])
assert status == 200 and theirs['author'] == beta['id'], theirs
status, authorless = request('/api/collections/comments/records', {'issue': issue['id'], 'body': 'no member wrote this'}, auth=su)
assert status == 200 and authorless['author'] == '', authorless
for target in [note, theirs, authorless]:
    path_c = '/api/collections/comments/records/' + target['id']
    status, refused = request(path_c, {'body': 'alpha put words here'}, 'PATCH', auth=alpha['token'])
    if target is note:  # a server record: no request edits it at all
        assert status == 400 and 'server-written comment cannot be edited' in refused['message'], refused
    else:
        assert status == 403 and "comment's author can change or delete it" in refused['message'], refused
    status, refused = request(path_c, method='DELETE', auth=alpha['token'])
    assert status == 403, (status, refused)
bodies = [c['body'] for c in state()['comments']]
assert note['body'] in bodies and 'beta said this' in bodies, bodies
n = next(i for i, c in enumerate(state()['comments'], 1) if c['id'] == theirs['id'])
for argv in [('issue', 'comment', 'edit', key, str(n), '--force', '-b', 'rewritten'),
             ('issue', 'comment', 'delete', key, str(n), '--force', '--yes')]:
    p = cli(*argv, actor=alpha)
    assert p.returncode != 0 and "comment's author can change or delete it" in p.stderr, (argv, p.stderr)
assert 'beta said this' in [c['body'] for c in state()['comments']]
status, edited = request('/api/collections/comments/records/' + theirs['id'], {'body': 'beta edited this'}, 'PATCH', auth=beta['token'])
assert status == 200 and edited['body'] == 'beta edited this', edited
status, _ = request('/api/collections/comments/records/' + theirs['id'], method='DELETE', auth=beta['token'])
assert status == 204, status
# The forced-release record is the server's record of the release, so even
# its author, the forcer, can neither rewrite nor delete it (LLL-512), and no
# request may set or clear server_record.
note_path = '/api/collections/comments/records/' + note['id']
status, refused = request(note_path, {'body': "beta released alice's claim at her request."}, 'PATCH', auth=beta['token'])
assert status == 400 and 'server-written comment cannot be edited' in refused['message'], refused
status, refused = request(note_path, {'server_record': False}, 'PATCH', auth=su)
assert status == 400, (status, refused)
status, refused = request(note_path, method='DELETE', auth=beta['token'])
assert status == 403 and 'only by an administrator' in refused['message'], (status, refused)
for who in [beta['token'], su]:
    status, refused = request('/api/collections/comments/records', {'issue': issue['id'], 'body': 'x', 'server_record': True}, auth=who)
    assert status == 400, (status, refused)
assert note['body'] in [c['body'] for c in state()['comments']]
p = cli('issue', 'view', key, '--raw')
assert p.returncode == 0 and "- **claim-beta** (" in p.stdout and '**system**' not in p.stdout, p.stdout
print('System comments: author_kind refused from any request, server-shaped member text stays the member\'s, forced releases read as the releaser')

# LLL-662 (b): 'issue next' reads the claims, not only the assignee. The
# holder may move the assignee off its own claimed issue; it is still held.
set_state('todo')
assert cli('issue', 'claim', key, actor=alpha).returncode == 0
status, moved = request('/api/collections/issues/records/' + issue['id'], {'assignee': ''}, 'PATCH', auth=alpha['token'])
assert status == 200 and state()['claim'] is not None and state()['assignee'] == '', moved
p = cli('issue', 'next')
assert key not in p.stdout, (p.stdout, p.stderr)
print('Next: a claimed issue with no assignee is not offered')

# LLL-662 (a): deleting an issue cascades its claim away, so a claimed issue
# is refused at the API for everyone, holder and superuser included, and the
# CLI's --force releases it first under the release rule.
for who in [alpha['token'], beta['token'], su]:
    status, refused = request('/api/collections/issues/records/' + issue['id'], method='DELETE', auth=who)
    assert status == 400 and 'claimed by' in refused['message'], (status, refused)
assert state()['claim'] is not None
p = cli('issue', 'delete', key, '--yes', actor=beta)
assert p.returncode != 0 and "'lll issue delete " + key + " --force'" in p.stderr, p.stderr
assert state()['claim'] is not None
spare = post('issues', {'team': team['id'], 'title': 'Unclaimed delete', 'state': 'todo'})
# LLL-679: --force on an unclaimed issue is unneeded, not a usage error.
p = cli('issue', 'delete', 'CLTX-' + str(spare['number']), '--force', '--yes', actor=beta)
assert p.returncode == 0 and 'Deleted CLTX-' in p.stdout, (p.returncode, p.stdout, p.stderr)
assert request('/api/collections/issues/records/' + spare['id'])[0] == 404
p = cli('issue', 'delete', key, '--force', '--yes', actor=beta)
assert p.returncode == 0 and 'Deleted ' + key in p.stdout, (p.stdout, p.stderr)
assert request('/api/collections/issues/records/' + issue['id'])[0] == 404
print('Delete: a claimed issue is refused at the API and by the CLI without --force; --force releases, then deletes')
