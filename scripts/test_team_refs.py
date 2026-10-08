#!/usr/bin/env python3
"""LLL-631, LLL-634, LLL-628 on a live board.

631: a reference stays inside one team for every writer (all-scope member,
superuser, raw team move), and the read-only audit lists legacy ones.
634: a team-scoped member cannot read hidden rows through a multi-match
relation filter, over the list endpoint, HEAD, or a realtime subscription.
628: a team key must match ^[A-Z][A-Z0-9_-]{0,15}$; a migration reports
legacy keys without rewriting them.
Legitimate same-team work keeps working throughout."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
repo = Path(__file__).resolve().parent.parent
RULE = '^[A-Z][A-Z0-9_-]{0,15}$'


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def call(base, path, body=None, token='', method=None):
    hdrs, data = {}, None
    if body is not None:
        hdrs['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    if token:
        hdrs['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, method=method, headers=hdrs, data=data)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        resp = e
    text = resp.read().decode()
    try:
        text = json.loads(text)
    except ValueError:
        pass
    return resp.status, text


def q(filter_):
    return urllib.parse.quote(filter_)


with tempfile.TemporaryDirectory(prefix='lll-631-') as directory:
    root = Path(directory)
    (root / 'home').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root / 'home'), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='board-owner', LLL_ADMIN_EMAIL='refs@example.invalid',
               LLL_ADMIN_PASSWORD='local-team-refs-password', LLL_BOARD_TOKEN='local-team-refs-board')
    log = root / 'up.log'
    up = [binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')]

    def start(log):
        with log.open('w') as output:
            return subprocess.Popen(up, cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)

    def stop(proc):
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()

    def db():
        return sqlite3.connect(root / 'data' / 'data.db', timeout=30)

    child = start(log)
    try:
        endpoint = wait_for_endpoints(log)
        api = endpoint['db_url']
        su = call(api, '/api/collections/_superusers/auth-with-password',
                  {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})[1]['token']
        alpha = next(t for t in call(api, '/api/collections/teams/records', token=su)[1]['items'] if t['key'] == 'ALPHA')
        beta = call(api, '/api/collections/teams/records', {'key': 'BETA', 'name': 'Bravo'}, su)[1]
        toks = {'su': su}

        def member(name, **access):
            body = {'name': name, 'email': f'{name}@example.test', 'password': 'pw12345678',
                    'passwordConfirm': 'pw12345678', 'kind': 'person', **access}
            code, rec = call(api, '/api/collections/members/records', body, su)
            assert code == 200, rec
            code, tok = call(api, f"/api/collections/members/impersonate/{rec['id']}", {'duration': 3600}, su)
            assert code == 200, tok
            toks[name] = tok['token']

        member('guest', scope='teams', teams=[alpha['id']], mode='rw')
        member('full', scope='all', mode='rw')

        def create(collection, who='su', **data):
            code, rec = call(api, f'/api/collections/{collection}/records', data, toks[who])
            assert code == 200, (collection, data, rec)
            return rec

        def patch(collection, rid, who, **data):
            return call(api, f'/api/collections/{collection}/records/{rid}', data, toks[who], 'PATCH')

        def refused(result, *want):
            code, body = result
            text = json.dumps(body)
            assert code == 400 and 'reference stays inside one team' in text, (code, body)
            for w in want:
                assert w in text, (w, body)

        ae = create('labels', name='ae', team=alpha['id'])
        secret = create('labels', name='secretbeta', team=beta['id'])
        bproj = create('projects', name='bproj', team=beta['id'], status='planned')
        aproj = create('projects', name='aproj', team=alpha['id'], status='planned')
        issue = create('issues', team=alpha['id'], title='alpha work', state='todo', labels=[ae['id']])
        hidden = create('issues', team=beta['id'], title='hiddentitle', state='todo')
        visible = create('issues', team=alpha['id'], title='visible blocker', state='todo')

        # --- LLL-631: the audit repros now fail, for every writer ---
        for who in ['full', 'su']:
            refused(patch('issues', issue['id'], who, **{'labels+': [secret['id']]}), secret['id'])
            refused(patch('issues', issue['id'], who, project=bproj['id']))
            refused(patch('issues', issue['id'], who, **{'blocked_by+': [hidden['id']]}))
        # A raw team move that would strand an ALPHA label: refused, and the
        # refusal says what to detach.
        refused(patch('issues', issue['id'], 'full', team=beta['id']), "label 'ae' (ALPHA)", 'from ALPHA to BETA', 'Detach')
        # Moving a label away from the issues that use it.
        refused(patch('labels', ae['id'], 'full', team=beta['id']), 'issues.labels of issue ALPHA-1')
        # The assignment route checks the same rule.
        code, body = call(api, f"/api/lll/issues/{issue['id']}/assignment",
                          {'claim_id': '', 'fields': {'assignee': '', 'labels': [secret['id']]}}, toks['full'], 'POST')
        assert code == 400 and 'reference stays inside one team' in json.dumps(body), (code, body)

        # Same-team work still works: labels, project, blockers, docs, a move.
        assert patch('issues', issue['id'], 'guest', project=aproj['id'])[0] == 200
        assert patch('issues', issue['id'], 'guest', **{'blocked_by+': [visible['id']]})[0] == 200
        assert patch('issues', issue['id'], 'full', **{'labels+': [ae['id']]})[0] == 200
        create('docs', who='full', team=alpha['id'], slug='d1', title='d', kind='note', body='b', issues=[issue['id']])
        loose = create('issues', team=alpha['id'], title='moves cleanly', state='todo')
        code, moved = patch('issues', loose['id'], 'full', team=beta['id'])
        assert code == 200 and moved['team'] == beta['id'], moved
        loose_label = create('labels', name='unused', team=alpha['id'])
        assert patch('labels', loose_label['id'], 'full', team=beta['id'])[0] == 200
        # CLI: the LLL-100 move verbs still refuse with their own message.
        cli_env = {**env, 'LLL_URL': api, 'LLL_TOKEN': toks['full']}

        def lll(*args):
            done = subprocess.run([binary, *args], cwd=root, env=cli_env, capture_output=True, text=True, timeout=60)
            return done.returncode, done.stdout + done.stderr

        code, out = lll('label', 'move', 'ae', '--to', 'BETA')
        assert code != 0 and 'ALPHA-1' in out, out

        # --- legacy data: what a board from before LLL-631 can hold ---
        with db() as conn:
            conn.execute('UPDATE issues SET labels = ? WHERE id = ?', (json.dumps([ae['id'], secret['id']]), issue['id']))
            conn.execute('UPDATE issues SET blocked_by = ? WHERE id = ?', (json.dumps([visible['id'], hidden['id']]), issue['id']))
        # An unrelated edit is not blocked by it.
        assert patch('issues', issue['id'], 'guest', title='alpha work edited')[0] == 200

        # The read-only audit lists exactly those references.
        def audit(who, *args):
            done = subprocess.run([sys.executable, str(repo / 'scripts' / 'audit_cross_team_refs.py'), *args],
                                  env={**env, 'LLL_URL': api, 'LLL_TOKEN': toks[who]}, capture_output=True, text=True, timeout=60)
            return done.returncode, done.stdout, done.stderr

        code, out, err = audit('full')
        assert code == 1, (code, out, err)
        assert "issue ALPHA-1 labels -> label 'secretbeta' (BETA)" in out and 'issue ALPHA-1 blocked_by -> issue BETA-1' in out, out
        assert '2 cross-team reference(s)' in err, err
        code, out, _ = audit('su', '--json')
        assert code == 1 and len(json.loads(out)) == 2, out
        code, _, err = audit('guest')
        assert code == 2 and 'sees only some teams' in err, err

        # --- LLL-634: the oracle is closed for a scoped member ---
        def listing(who, filter_='', sort='', method=None):
            path = '/api/collections/issues/records?perPage=50'
            if filter_:
                path += '&filter=' + q(filter_)
            if sort:
                path += '&sort=' + q(sort)
            return call(api, path, token=toks[who], method=method)

        probes = ['labels.name ~ "%e%"', 'labels.name ~ "ae%"', 'blocked_by.title ~ "%i%"', 'blocked_by.title ~ "%visible%"',
                  'labels.name !~ "zz"', 'labels.name:lower = "secretbeta"', '@collection.labels.name != "secretbeta"',
                  '@collection.issues.title !~ "hidden%"', 'labels ~ "a"', 'labels:length = 2', 'project ~ "a"']
        for probe in probes:
            code, body = listing('guest', probe)
            assert code == 403 and 'limited to some teams' in body['message'], (probe, code, body)
            control = listing('full', probe)
            # PocketBase itself keeps @collection to superusers.
            assert control[0] == 200 or 'Only superusers' in str(control[1]), ('control: full access may filter', probe, control)
        for sort in ['labels.name', '-blocked_by.title', 'labels', '@collection.labels.name']:
            assert listing('guest', sort=sort)[0] == 403, sort
        # HEAD is served by the list handler too; its Content-Length must not answer.
        code, _ = listing('guest', 'labels.name ~ "%e%"', method='HEAD')
        assert code == 403, code
        # Legitimate scoped filters.
        for allowed, count in [('state = "todo"', 2), (f'labels.id ?= "{ae["id"]}"', 1), ('labels.name ?~ "ae"', 1),
                               ('labels.name ?~ "secret"', 0), (f'blocked_by.id ?= "{visible["id"]}"', 1),
                               (f'project = "{aproj["id"]}"', 1), ('project.name ~ "aproj"', 1), ('title ~ "alpha"', 1)]:
            code, body = listing('guest', allowed)
            assert code == 200 and body['totalItems'] == count, (allowed, code, body)
        code, body = listing('guest', sort='-created')
        assert code == 200

        # Realtime: the same filter in subscription options is refused.
        def realtime_subscribe(token, topic):
            resp = urllib.request.urlopen(urllib.request.Request(api + '/api/realtime'), timeout=10)
            client = None
            while client is None:
                line = resp.readline().decode()
                if line.startswith('data:'):
                    client = json.loads(line[5:])['clientId']
            code, body = call(api, '/api/realtime', {'clientId': client, 'subscriptions': [topic]}, token)
            resp.close()
            return code, body

        options = q(json.dumps({'query': {'filter': 'labels.name ~ "%e%"'}}))
        for topic in [f'issues/*?options={options}', f'issues/*?x=1&opt%69ons={options}', f"issues/{issue['id']}?options={options}"]:
            assert realtime_subscribe(toks['guest'], topic)[0] == 403, topic
        assert realtime_subscribe(toks['full'], f'issues/*?options={options}')[0] == 204
        ok = q(json.dumps({'query': {'filter': f'team = "{alpha["id"]}"'}}))
        assert realtime_subscribe(toks['guest'], f'issues/*?options={ok}')[0] == 204

        # Detach the legacy references; the audit comes back clean.
        assert patch('issues', issue['id'], 'full', **{'labels-': [secret['id']], 'blocked_by-': [hidden['id']]})[0] == 200
        code, out, err = audit('full')
        assert code == 0 and out == '', (code, out, err)

        # --- LLL-628: the team key rule ---
        code, body = call(api, '/api/collections/teams/records', {'key': 'q"<b>$(id)', 'name': 'x'}, toks['full'])
        assert code == 400 and RULE in json.dumps(body), (code, body)
        for bad in ['2ENG', 'A' * 17, 'a b', 'ÉQUIPE', '']:
            assert call(api, '/api/collections/teams/records', {'key': bad}, su)[0] == 400, bad
        code, out = lll('team', 'create', '-k', 'q"<b>$(id)', '-n', 'x')
        assert code != 0 and RULE in out and '$(ID)' not in out, out
        code, out = lll('team', 'rename', 'BETA', '-k', 'be ta')
        assert code != 0 and RULE in out, out
        code, body = call(api, f"/api/collections/teams/records/{beta['id']}", {'key': 'x y'}, su, 'PATCH')
        assert code == 400 and RULE in json.dumps(body), body
        code, out = lll('team', 'create', '-k', 'web-2', '-n', 'Web')
        assert code == 0 and 'WEB-2' in out, out
        code, body = call(api, '/api/collections/teams/records', {'key': 'ops_1'}, toks['full'])
        assert code == 200 and body['key'] == 'OPS_1', body

        # A legacy bad key: the migration reports it, rewrites nothing, and
        # the team still takes unrelated edits.
        legacy = create('teams', key='LEGACY')
        stop(child)
        with db() as conn:
            conn.execute('UPDATE teams SET key = ? WHERE id = ?', ('BAD KEY$(X)', legacy['id']))
            conn.execute("DELETE FROM _migrations WHERE file = '1792100000_report_bad_team_keys.js'")
        log = root / 'up2.log'
        child = start(log)
        endpoint = wait_for_endpoints(log)
        api = endpoint['db_url']
        text = log.read_text()
        assert f'LLL-628: team {legacy["id"]} has key "BAD KEY$(X)"' in text, text[-2000:]
        su = call(api, '/api/collections/_superusers/auth-with-password',
                  {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})[1]['token']
        code, body = call(api, f"/api/collections/teams/records/{legacy['id']}", {'name': 'renamed only'}, su, 'PATCH')
        assert code == 200 and body['key'] == 'BAD KEY$(X)', body
        code, body = call(api, f"/api/collections/teams/records/{legacy['id']}", {'key': 'LEGACY'}, su, 'PATCH')
        assert code == 200 and body['key'] == 'LEGACY', body
    finally:
        stop(child)
print('team refs: ok')
