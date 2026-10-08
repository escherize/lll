#!/usr/bin/env python3
"""LLL-658 differential: the board reads as its viewer, and nobody sees
anything new.

Usage: test_viewer_reads_differential.py OLD_LLL NEW_LLL

OLD_LLL is a board from before LLL-658 (v0.9.0, which read as its own member
and filtered by hand); NEW_LLL reads with each viewer's own credential. One
board is seeded once (teams ALPHA and BETA, a cross-team label, project and
doc link planted the way a pre-LLL-631 board can hold them, members hidden
from ALPHA's guests) and served by OLD, then by NEW on the same database.
Every board page, raw view, search and live fragment is fetched for five
viewers on each:

  rw-guest    member cookie, team ALPHA, read-write
  ro-guest    member cookie, team ALPHA, read-only
  link        the KEY.MAC team link for ALPHA
  full-member member cookie, every team
  board-token the board token

Each response is reduced to the set of seeded markers (names, titles, keys
and record ids) it contains. A scoped viewer must see no marker under NEW
that it did not see under OLD, and no BETA or hidden-member marker at all;
a full viewer must see exactly the markers it saw under OLD. Status codes
must agree. This is not part of the gate: it needs the old binary."""
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from board_startup import wait_for_endpoints  # noqa: E402

OLD, NEW = (str(Path(p).resolve()) for p in sys.argv[1:3])
BOARD_TOKEN = 'local-differential-board'


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


raw = urllib.request.build_opener(NoRedirect)


def call(base, path, body=None, token='', method=None, headers=None):
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        hdrs['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    if token:
        hdrs['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, method=method, headers=hdrs, data=data)
    try:
        resp = raw.open(req, timeout=20)
    except urllib.error.HTTPError as e:
        resp = e
    text = resp.read().decode()
    try:
        return resp.status, json.loads(text)
    except ValueError:
        return resp.status, text


def boot(binary, root, env, name):
    log = root / f'{name}.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    endpoint = wait_for_endpoints(log)
    return child, endpoint['db_url'], endpoint['board_url']


def stop(child):
    child.terminate()
    try:
        child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()


def seed(api, root, env):
    su = call(api, '/api/collections/_superusers/auth-with-password',
              {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})[1]['token']

    def make(collection, body):
        code, rec = call(api, f'/api/collections/{collection}/records', body, su)
        assert code == 200, (collection, code, rec)
        return rec

    alpha = next(t for t in call(api, '/api/collections/teams/records', token=su)[1]['items'] if t['key'] == 'ALPHA')
    beta = make('teams', {'key': 'BETA', 'name': 'Bravo Hidden Team'})

    def member(name, **fields):
        rec = make('members', {'name': name, 'email': f'{name}@example.test', 'password': 'pw12345678',
                               'passwordConfirm': 'pw12345678', 'kind': 'person', **fields})
        code, tok = call(api, f"/api/collections/members/impersonate/{rec['id']}", {'duration': 86400}, su)
        assert code == 200, tok
        return rec, tok['token']

    rw, rw_tok = member('alpha-writer', scope='teams', teams=[alpha['id']], mode='rw')
    ro, ro_tok = member('alpha-reader', scope='teams', teams=[alpha['id']], mode='ro')
    full, full_tok = member('full-person', scope='all', mode='rw')
    bonly, _ = member('beta-only', scope='teams', teams=[beta['id']], mode='rw')
    bbot, _ = member('bot-beta', scope='teams', teams=[beta['id']], mode='rw', kind='bot')

    alabel = make('labels', {'team': alpha['id'], 'name': 'alphalabel', 'color': '#336699'})
    blabel = make('labels', {'team': beta['id'], 'name': 'zlabelhidden', 'color': '#993366'})
    aproj = make('projects', {'team': alpha['id'], 'name': 'alphaproj', 'status': 'started'})
    bproj = make('projects', {'team': beta['id'], 'name': 'zprojhidden', 'status': 'started'})
    a1 = make('issues', {'team': alpha['id'], 'title': 'alpha work', 'state': 'todo', 'assignee': full['id'],
                         'labels': [alabel['id']], 'project': aproj['id'], 'description': 'alpha body text'})
    a2 = make('issues', {'team': alpha['id'], 'title': 'alpha second', 'state': 'in-progress'})
    b1 = make('issues', {'team': beta['id'], 'title': 'zebra hidden plan', 'state': 'todo', 'labels': [blabel['id']],
                         'project': bproj['id']})
    bcom = make('comments', {'issue': b1['id'], 'body': 'zebra comment'})
    acom = make('comments', {'issue': a1['id'], 'body': 'alpha comment by a hidden bot', 'author': bbot['id']})
    bdoc = make('docs', {'team': beta['id'], 'slug': 'bdoc', 'title': 'zebradoc', 'kind': 'note', 'body': 'zebradoc body'})
    cross = make('docs', {'team': alpha['id'], 'slug': 'cross', 'title': 'crossdoc', 'kind': 'note', 'body': 'alpha doc body',
                          'issues': [a1['id']], 'author': bonly['id']})

    # Legacy shapes LLL-631 now refuses at the API, written straight to the
    # database: another team's label and project on an ALPHA issue, a BETA
    # issue linked from an ALPHA doc.
    with sqlite3.connect(root / 'data' / 'data.db', timeout=30) as conn:
        conn.execute('UPDATE issues SET labels = ? WHERE id = ?', (json.dumps([alabel['id'], blabel['id']]), a1['id']))
        conn.execute('UPDATE issues SET project = ?, assignee = ? WHERE id = ?', (bproj['id'], bonly['id'], a2['id']))
        conn.execute('UPDATE docs SET issues = ? WHERE id = ?', (json.dumps([a1['id'], b1['id']]), cross['id']))

    link = 'ALPHA.' + hmac.new(BOARD_TOKEN.encode(), b'ALPHA', hashlib.sha256).hexdigest()
    hidden = {
        'BETA key': 'BETA', 'BETA name': 'Bravo Hidden Team', 'BETA title': 'zebra hidden plan', 'BETA live title': 'zebra live edit', 'BETA comment': 'zebra comment', 'BETA live comment': 'zebra live comment', 'BETA doc': 'zebradoc', 'BETA label': 'zlabelhidden',
        'BETA project': 'zprojhidden', 'beta-only name': 'beta-only', 'bot-beta name': 'bot-beta',
        'beta team id': beta['id'], 'BETA-1 id': b1['id'], 'beta comment id': bcom['id'], 'beta doc id': bdoc['id'],
        'beta label id': blabel['id'], 'beta project id': bproj['id'], 'beta-only id': bonly['id'],
        'bot-beta id': bbot['id'],
    }
    visible = {
        'ALPHA-1 title': 'alpha work', 'ALPHA-2 title': 'alpha second', 'alpha label': 'alphalabel',
        'alpha project': 'alphaproj', 'full-person': 'full-person', 'alpha-writer': 'alpha-writer',
        'alpha-reader': 'alpha-reader', 'alpha comment': 'alpha comment by a hidden bot', 'cross doc': 'crossdoc',
        'hidden member': 'hidden member', 'ALPHA-1 id': a1['id'], 'ALPHA-2 id': a2['id'],
        'alpha label id': alabel['id'], 'alpha project id': aproj['id'], 'full-person id': full['id'],
        'alpha comment id': acom['id'], 'live title': 'alpha live edit', 'live comment': 'alpha live comment',
    }
    return {
        'su_creds': (env['LLL_ADMIN_EMAIL'], env['LLL_ADMIN_PASSWORD']),
        'viewers': {'rw-guest': rw_tok, 'ro-guest': ro_tok, 'link': link, 'full-member': full_tok,
                    'board-token': BOARD_TOKEN},
        'scoped': {'rw-guest', 'ro-guest', 'link'},
        'a1': a1['id'], 'b1': b1['id'], 'hidden': hidden, 'markers': {**hidden, **visible},
    }


PAGES = [
    '/t/ALPHA/', '/t/ALPHA/?raw', '/t/ALPHA/issues', '/t/ALPHA/issues?raw', '/t/ALPHA/projects',
    '/t/ALPHA/projects?raw', '/t/ALPHA/docs', '/t/ALPHA/docs?raw', '/t/ALPHA/doc/cross', '/t/ALPHA/doc/cross?raw',
    '/t/ALPHA/issue/ALPHA-1', '/t/ALPHA/issue/ALPHA-1?raw', '/t/ALPHA/issue/ALPHA-2', '/t/ALPHA/issue/ALPHA-2?raw',
    '/t/ALPHA/search?q=alpha', '/t/ALPHA/search?q=alpha&raw', '/t/ALPHA/search?q=alpha&fragment=1',
    '/t/ALPHA/search?q=alpha&palette=1', '/t/ALPHA/search?q=zebra&raw', '/t/ALPHA/search?q=zlabelhidden&raw',
    '/t/ALPHA/search?q=zprojhidden&raw', '/t/ALPHA/search?q=bot-beta&raw', '/t/ALPHA/?assignee=beta-only',
    '/t/ALPHA/issues?assignee=beta-only&raw', '/t/ALPHA/?label=zlabelhidden', '/t/ALPHA/?project=zprojhidden',
    '/t/BETA/', '/t/BETA/?raw', '/t/BETA/issue/BETA-1', '/t/ALPHA/issue/BETA-1', '/issue/BETA-1', '/issue/ALPHA-1',
    '/t/BETA/doc/bdoc', '/t/BETA/docs?raw', '/t/BETA/search?q=zebra&raw', '/t/NOPE/', '/',
    '/attachments/file?key=BETA-1&file=x.png',
]
STREAMS = ['/events?team=ALPHA', '/events?page=issue&key=ALPHA-1', '/events?page=issue&key=ALPHA-2']


def markers_in(text, markers, path=''):
    """The markers in a response. A marker the request itself names (a
    hidden key in the URL, a searched word) is echoed by refusals and search
    headings alike, so it says nothing about what the viewer was shown."""
    asked = urllib.parse.unquote(path).lower()
    return {name for name, needle in markers.items() if needle in text and needle.lower() not in asked}


def capture(binary, root, env, data, name):
    """Every page and stream for every viewer, as (status, marker set)."""
    child, api, board = boot(binary, root, env, name)
    procs = []
    try:
        su = call(api, '/api/collections/_superusers/auth-with-password',
                  {'identity': data['su_creds'][0], 'password': data['su_creds'][1]})[1]['token']
        # The same starting point for both runs.
        call(api, f"/api/collections/issues/records/{data['a1']}", {'title': 'alpha work'}, su, 'PATCH')
        call(api, f"/api/collections/issues/records/{data['b1']}", {'title': 'zebra hidden plan'}, su, 'PATCH')
        for body in ['alpha live comment', 'zebra live comment']:
            q = urllib.parse.quote(f"body='{body}'")
            for c in call(api, f'/api/collections/comments/records?perPage=200&filter={q}', token=su)[1]['items']:
                call(api, f"/api/collections/comments/records/{c['id']}", token=su, method='DELETE')
        out = {}
        for viewer, tok in data['viewers'].items():
            for path in PAGES:
                code, body = call(board, path, headers={'Cookie': 'lll_board=' + tok})
                text = body if isinstance(body, str) else json.dumps(body)
                if code in (301, 302, 303):
                    text = ''
                out[(viewer, path)] = (code, markers_in(text, data['markers'], path))
        streams = {}
        for viewer, tok in data['viewers'].items():
            for path in STREAMS:
                f = root / f'{name}-{viewer}-{len(streams)}.sse'
                handle = f.open('w')
                procs.append(subprocess.Popen(['curl', '-sN', '-H', f'Cookie: lll_board={tok}', board + path],
                                              stdout=handle, stderr=subprocess.DEVNULL, start_new_session=True))
                streams[(viewer, 'SSE ' + path)] = f
        time.sleep(3)
        # BETA changes, then ALPHA ones: a scoped stream must never carry the
        # first kind; every stream that shows ALPHA must carry the second.
        call(api, f"/api/collections/issues/records/{data['b1']}", {'title': 'zebra live edit'}, su, 'PATCH')
        call(api, '/api/collections/comments/records', {'issue': data['b1'], 'body': 'zebra live comment'}, su)
        call(api, f"/api/collections/issues/records/{data['a1']}", {'title': 'alpha live edit'}, su, 'PATCH')
        call(api, '/api/collections/comments/records', {'issue': data['a1'], 'body': 'alpha live comment'}, su)
        time.sleep(5)
        for key, f in streams.items():
            out[key] = (200, markers_in(f.read_text(), data['markers'], key[1]))
        return out
    finally:
        for proc in procs:
            proc.terminate()
        stop(child)


with tempfile.TemporaryDirectory(prefix='lll-658-diff-') as directory:
    root = Path(directory)
    (root / 'home').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root / 'home'), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='board-owner', LLL_ADMIN_EMAIL='diff@example.invalid',
               LLL_ADMIN_PASSWORD='local-differential-password', LLL_BOARD_TOKEN=BOARD_TOKEN)
    child, api, _ = boot(OLD, root, env, 'seed')
    try:
        data = seed(api, root, env)
    finally:
        stop(child)
    old = capture(OLD, root, env, data, 'old')
    new = capture(NEW, root, env, data, 'new')

# Status changes that are the point, not a regression. v0.9.0's gate routed
# a member with access to every team like any scoped login, so another
# team's issue under the wrong team's URL was a 404 for it; reading as that
# member, it gets the redirect the board token gets (LLL-664).
EXPECTED = {('full-member', '/t/ALPHA/issue/BETA-1'): (404, 303)}

failures = []
fewer = []
for key in sorted(old):
    viewer, path = key
    (ocode, oset), (ncode, nset) = old[key], new[key]
    if ocode != ncode and EXPECTED.get(key) == (ocode, ncode):
        fewer.append(f'{viewer:12} {path}: status {ocode} -> {ncode}, expected')
    elif ocode != ncode:
        failures.append(f'{viewer:12} {path}: status {ocode} -> {ncode}')
    if viewer in data['scoped']:
        leaked = nset & set(data['hidden'])
        if leaked:
            failures.append(f'{viewer:12} {path}: LEAK {sorted(leaked)}')
        if nset - oset:
            failures.append(f'{viewer:12} {path}: sees more than before {sorted(nset - oset)}')
        if oset - nset:
            fewer.append(f'{viewer:12} {path}: sees less than before {sorted(oset - nset)}')
    elif nset != oset:
        failures.append(f'{viewer:12} {path}: full view changed, lost {sorted(oset - nset)} gained {sorted(nset - oset)}')

# Controls, so an empty capture cannot pass: the full viewers saw BETA, the
# scoped ones saw ALPHA and the live ALPHA edit, under both binaries.
for run, got in [('old', old), ('new', new)]:
    for viewer in data['viewers']:
        assert 'ALPHA-1 title' in got[(viewer, '/t/ALPHA/')][1], (run, viewer, 'board page lost ALPHA-1')
        assert 'live title' in got[(viewer, 'SSE /events?team=ALPHA')][1], (run, viewer, 'board stream lost the live edit')
        assert 'live comment' in got[(viewer, 'SSE /events?page=issue&key=ALPHA-1')][1], (run, viewer, 'issue stream lost the comment')
    for viewer in ['full-member', 'board-token']:
        assert 'BETA title' in got[(viewer, '/t/BETA/')][1], (run, viewer, 'control: full viewer lost BETA')

compared = len(old)
print(f'compared {compared} (viewer, page or stream) pairs across {len(data["viewers"])} viewers')
for line in fewer:
    print('note:', line)
if failures:
    for line in failures:
        print('FAIL:', line)
    sys.exit(1)
print('viewer reads differential: ok (scoped viewers see no more than v0.9.0, full viewers see the same)')
