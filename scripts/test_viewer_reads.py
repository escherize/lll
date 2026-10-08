#!/usr/bin/env python3
"""LLL-658: the board reads as its viewer.

- A KEY.MAC team link reads as its team's link viewer: its pages, search and
  live stream carry ALPHA and never BETA, though the board's own member sees
  both. The reader's token stays on the server.
- /api/lll/link-token answers only a caller that sees every team.
- One page load asks /api/lll/access once (PocketBase's request log).
- A member viewer's live issue fragment names the viewer as claim actor."""
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
BOARD_TOKEN = 'local-viewer-reads-board'
HIDDEN = ['BETA', 'Bravo Hidden Team', 'zebra']


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
        resp = raw.open(req, timeout=15)
    except urllib.error.HTTPError as e:
        resp = e
    text = resp.read().decode()
    try:
        text = json.loads(text)
    except ValueError:
        pass
    return resp.status, text, resp.headers


with tempfile.TemporaryDirectory(prefix='lll-658-') as directory:
    root = Path(directory)
    (root / 'home').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root / 'home'), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='board-owner', LLL_ADMIN_EMAIL='reads@example.invalid',
               LLL_ADMIN_PASSWORD='local-viewer-reads-password', LLL_BOARD_TOKEN=BOARD_TOKEN)
    log = root / 'up.log'
    streams = []
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        endpoint = wait_for_endpoints(log)
        api, board = endpoint['db_url'], endpoint['board_url']
        su = call(api, '/api/collections/_superusers/auth-with-password',
                  {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})[1]['token']
        alpha = next(t for t in call(api, '/api/collections/teams/records', token=su)[1]['items'] if t['key'] == 'ALPHA')
        beta = call(api, '/api/collections/teams/records', {'key': 'BETA', 'name': 'Bravo Hidden Team'}, su)[1]
        ia = call(api, '/api/collections/issues/records', {'team': alpha['id'], 'title': 'alpha work', 'state': 'todo'}, su)[1]
        ib = call(api, '/api/collections/issues/records', {'team': beta['id'], 'title': 'zebra hidden plan', 'state': 'todo'}, su)[1]

        def member(name, **access):
            body = {'name': name, 'email': f'{name}@example.test', 'password': 'pw12345678',
                    'passwordConfirm': 'pw12345678', 'kind': 'person', **access}
            code, rec, _ = call(api, '/api/collections/members/records', body, su)
            assert code == 200, rec
            return rec, call(api, f"/api/collections/members/impersonate/{rec['id']}", {'duration': 3600}, su)[1]['token']

        guest, guest_tok = member('alpha-guest', scope='teams', teams=[alpha['id']], mode='rw')
        link = 'ALPHA.' + hmac.new(BOARD_TOKEN.encode(), b'ALPHA', hashlib.sha256).hexdigest()

        def page(path, tok):
            return call(board, path, headers={'Cookie': 'lll_board=' + tok})

        # --- a team link reads as its team's link viewer ---
        for path in ['/t/ALPHA/', '/t/ALPHA/?raw', '/t/ALPHA/issues', '/t/ALPHA/issue/ALPHA-1',
                     '/t/ALPHA/issue/ALPHA-1?raw', '/t/ALPHA/search?q=alpha&raw', '/t/ALPHA/docs?raw']:
            code, body, headers = page(path, link)
            assert code == 200 and ('alpha work' in body or path.endswith('docs?raw')), (path, code)
            for marker in HIDDEN:
                assert marker not in body, f'link {path} leaked {marker!r}'
            # The link viewer's PocketBase token never reaches the browser.
            assert 'eyJ' not in body and 'eyJ' not in str(headers), f'link {path} carries a token'
        for path in ['/t/BETA/', '/t/BETA', '/t/ALPHA/issue/BETA-1', '/issue/BETA-1', '/events?team=BETA',
                     '/events?page=issue&key=BETA-1', '/t/BETA/search?q=zebra']:
            assert page(path, link)[0] == 404, path
        assert 'zebra' in page('/t/BETA/', BOARD_TOKEN)[1], 'control: the board token sees BETA'

        # --- the link's live stream: ALPHA arrives, BETA never does ---
        out = root / 'link.sse'
        streams.append(subprocess.Popen(['curl', '-sN', '-H', f'Cookie: lll_board={link}', board + '/events?team=ALPHA'],
                                        stdout=out.open('w'), stderr=subprocess.DEVNULL, start_new_session=True))
        gout = root / 'guest-issue.sse'
        streams.append(subprocess.Popen(['curl', '-sN', '-H', f'Cookie: lll_board={guest_tok}',
                                         board + '/events?page=issue&key=ALPHA-1'],
                                        stdout=gout.open('w'), stderr=subprocess.DEVNULL, start_new_session=True))

        def wait_for(path, needle):
            deadline = time.monotonic() + 15
            while needle not in path.read_text() and time.monotonic() < deadline:
                time.sleep(.1)
            assert needle in path.read_text(), f'{path.name}: never saw {needle!r}'

        wait_for(out, 'alpha work')
        wait_for(gout, 'alpha work')
        call(api, f"/api/collections/issues/records/{ib['id']}", {'title': 'zebra moved'}, su, 'PATCH')
        call(api, f"/api/collections/issues/records/{ia['id']}", {'title': 'alpha moved'}, su, 'PATCH')
        wait_for(out, 'alpha moved')
        wait_for(gout, 'alpha moved')
        time.sleep(.5)
        for marker in HIDDEN:
            assert marker not in out.read_text(), f'link stream leaked {marker!r}'
        # Read as the guest, the live detail offers the guest's own claim.
        assert 'Claim as alpha-guest' in gout.read_text(), 'live issue fragment does not name the viewer'

        # --- only a caller that sees every team gets a link reader ---
        assert call(api, '/api/lll/link-token', {'team': 'ALPHA'}, guest_tok)[0] == 403, 'a scoped member got a link token'
        assert call(api, '/api/lll/link-token', {'team': 'ALPHA'})[0] in (401, 403), 'anonymous got a link token'
        code, minted, _ = call(api, '/api/lll/link-token', {'team': 'ALPHA'}, su)
        assert code == 200 and minted['token'], minted
        assert call(api, '/api/lll/link-token', {'team': 'NOPE'}, su)[0] == 404
        # The reader reads ALPHA and nothing of BETA, and writes nothing.
        reader = minted['token']
        teams = call(api, '/api/collections/teams/records', token=reader)[1]['items']
        assert [t['key'] for t in teams] == ['ALPHA'], teams
        assert call(api, f"/api/collections/issues/records/{ib['id']}", token=reader)[0] == 404
        assert call(api, f"/api/collections/issues/records/{ia['id']}", {'title': 'x'}, reader, 'PATCH')[0] in (403, 404)
        assert call(api, '/api/collections/link_viewers/auth-with-password',
                    {'identity': f"{alpha['id']}@links.invalid", 'password': 'x'})[0] >= 400

        # --- one access check per page load ---
        def access_calls():
            q = urllib.parse.quote("data.url~'/api/lll/access'")
            return call(api, f'/api/logs?perPage=1&filter={q}', token=su)[1]['totalItems']

        time.sleep(3)
        before = access_calls()
        assert page('/t/ALPHA/issue/ALPHA-1', guest_tok)[0] == 200
        deadline = time.monotonic() + 10
        while access_calls() == before and time.monotonic() < deadline:
            time.sleep(.5)
        time.sleep(2)
        assert access_calls() - before == 1, f'one issue page asked /api/lll/access {access_calls() - before} times'
    finally:
        for proc in streams:
            proc.terminate()
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
print('viewer reads: ok')
