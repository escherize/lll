#!/usr/bin/env python3
"""A member invited with --team sees only that team: over the API (collection
rules and the custom /api/lll routes) and on the board (the scoped link)."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


raw = urllib.request.build_opener(NoRedirect)


def call(base, path, body=None, token='', method=None, headers=None):
    """(status, parsed-or-text body, response headers). Never raises on HTTP errors."""
    hdrs = {'Content-Type': 'application/json', **(headers or {})}
    if token:
        hdrs['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, method=method, headers=hdrs,
                                 data=None if body is None else json.dumps(body).encode())
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


with tempfile.TemporaryDirectory(prefix='lll-team-scope-') as directory:
    root = Path(directory)
    home = root / 'home'
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(home), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='scope-owner', LLL_ADMIN_EMAIL='scope@example.invalid',
               LLL_ADMIN_PASSWORD='local-team-scope-password', LLL_BOARD_TOKEN='local-team-scope-board')
    log = root / 'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        endpoint = wait_for_endpoints(log)
        api, board = endpoint['db_url'], endpoint['board_url']
        _, su, _ = call(api, '/api/collections/_superusers/auth-with-password',
                        {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})
        su = su['token']
        _, teams, _ = call(api, '/api/collections/teams/records', token=su)
        alpha = next(t for t in teams['items'] if t['key'] == 'ALPHA')
        _, beta, _ = call(api, '/api/collections/teams/records', {'key': 'BETA', 'name': 'Beta'}, su)
        _, ia, _ = call(api, '/api/collections/issues/records',
                        {'team': alpha['id'], 'title': 'alpha work', 'state': 'todo'}, su)
        _, ib, _ = call(api, '/api/collections/issues/records',
                        {'team': beta['id'], 'title': 'beta secret', 'state': 'todo'}, su,
                        headers={'Idempotency-Key': 'beta-once'})
        call(api, '/api/collections/comments/records', {'issue': ib['id'], 'body': 'beta comment'}, su)

        # The invite: one command, scoped to ALPHA, printing a scoped board link.
        cli = dict(env, LLL_URL=api, LLL_WEB_URL=board, LC_ALL='C')
        out = subprocess.run([binary, 'member', 'invite', 'guest', '--email', 'guest@example.test', '--team', 'alpha'],
                             cwd=root, env=cli, text=True, capture_output=True, timeout=30)
        assert out.returncode == 0, out.stdout + out.stderr
        assert 'limited to team ALPHA' in out.stdout, out.stdout
        password = re.search(r'temporary password: (\S+)', out.stdout).group(1)
        link = re.search(r'read-only board for ALPHA: (\S+)', out.stdout).group(1)
        assert link.startswith(board + '/t/ALPHA/?board_token=ALPHA.'), link
        assert env['LLL_BOARD_TOKEN'] not in link, 'scoped link leaked the full board token'

        _, auth, _ = call(api, '/api/collections/members/auth-with-password',
                          {'identity': 'guest@example.test', 'password': password})
        tok, me = auth['token'], auth['record']['id']
        assert auth['record']['teams'] == [alpha['id']], auth['record']

        def status(path, body=None, method=None, headers=None):
            return call(api, path, body, tok, method, headers)[0]

        def items(path):
            return call(api, path, token=tok)[1]['items']

        # Reads stay inside ALPHA.
        assert [t['key'] for t in items('/api/collections/teams/records')] == ['ALPHA']
        assert [i['title'] for i in items('/api/collections/issues/records')] == ['alpha work']
        assert items('/api/collections/comments/records') == []
        assert status(f"/api/collections/issues/records/{ib['id']}") == 404
        # Writes cannot reach or move into BETA.
        assert status('/api/collections/issues/records', {'team': beta['id'], 'title': 'x', 'state': 'todo'}) == 400
        assert status('/api/collections/issues/records', {'team': alpha['id'], 'title': 'ok', 'state': 'todo'}) == 200
        assert status(f"/api/collections/issues/records/{ia['id']}", {'team': beta['id']}, 'PATCH') == 404
        assert status(f"/api/collections/issues/records/{ia['id']}", {'title': 'alpha edited'}, 'PATCH') == 200
        assert status('/api/collections/comments/records', {'issue': ib['id'], 'body': 'x'}) == 400
        # A replayed Idempotency-Key must not hand back BETA's issue.
        replay = call(api, '/api/collections/issues/records', {'team': beta['id'], 'title': 'beta secret', 'state': 'todo'},
                      tok, headers={'Idempotency-Key': 'beta-once'})
        assert replay[0] == 400 and 'beta secret' not in json.dumps(replay[1]), replay
        # No widening its own scope, no minting members or teams.
        assert status(f'/api/collections/members/records/{me}', {'teams': []}, 'PATCH') == 404
        assert status(f'/api/collections/members/records/{me}', {'name': 'guest2'}, 'PATCH') == 200
        assert status('/api/collections/members/records', {'name': 'evil', 'email': 'e@example.test', 'password': 'pw12345678',
                                                           'passwordConfirm': 'pw12345678', 'kind': 'person'}) == 400
        assert status('/api/collections/teams/records', {'key': 'ZETA', 'name': 'z'}) == 400
        # The custom routes read through the app, past the rules; they check too.
        assert status(f"/api/lll/issues/{ib['id']}/claim", {}) == 404
        assert status(f"/api/lll/issues/{ib['id']}/refs", {'ref': 'https://example.test/pr/1'}) == 404
        assert status(f"/api/lll/issues/{ia['id']}/claim", {}) == 200

        # The board: the link logs in, then only ALPHA's read-only pages answer.
        code, _, headers = call(board, link[len(board):])
        assert code == 303, code
        cookie = headers['Set-Cookie'].split(';')[0]
        assert cookie.startswith('lll_board=ALPHA.'), cookie

        def page(path, method=None):
            return call(board, path, {} if method == 'POST' else None, method=method, headers={'Cookie': cookie})

        code, body, _ = page('/t/ALPHA/')
        assert code == 200 and 'alpha edited' in body and 'beta secret' not in body
        assert 'BETA' not in body, 'rail still lists the other team'
        assert page('/')[0] == 303
        for path in ['/t/BETA/', '/t/ALPHA/settings/identity', '/t/ALPHA/issue/BETA-1', '/issue/BETA-1',
                     '/search?q=beta', '/events?team=BETA']:
            assert page(path)[0] == 403, path
        assert page('/t/ALPHA/issue/ALPHA-1')[0] == 200
        assert page('/state', 'POST')[0] == 403
        # The full board token still opens everything.
        full = {'Cookie': 'lll_board=' + env['LLL_BOARD_TOKEN']}
        assert call(board, '/t/BETA/', headers=full)[0] == 200
        # A doc on ALPHA linking BETA's issue: the board renders links as its own
        # member, so a scoped viewer must not get BETA's key or title from it.
        _, doc, _ = call(api, '/api/collections/docs/records', {'team': alpha['id'], 'slug': 'cross', 'title': 'cross',
                                                                'kind': 'note', 'body': 'b', 'issues': [ia['id'], ib['id']]}, su)
        assert doc.get('id'), doc
        code, body, _ = page('/t/ALPHA/doc/cross?raw')
        assert code == 200 and 'ALPHA-1' in body and 'BETA-1' not in body, body
        assert 'BETA-1' in call(board, '/t/ALPHA/doc/cross?raw', headers=full)[1]
        # Deleting ALPHA would empty guest's teams, and empty means every team.
        assert call(api, f"/api/collections/teams/records/{alpha['id']}", token=su, method='DELETE')[0] == 400
        _, gamma, _ = call(api, '/api/collections/teams/records', {'key': 'GAMMA', 'name': 'g'}, su)
        assert call(api, f"/api/collections/teams/records/{gamma['id']}", token=su, method='DELETE')[0] == 204
        assert [t['key'] for t in items('/api/collections/teams/records')] == ['ALPHA']
        # Controls: the negatives above would pass vacuously if these did not hold.
        assert 'BETA' in call(board, '/t/ALPHA/', headers=full)[1], 'rail check proves nothing'
        su_replay = call(api, '/api/collections/issues/records', {'team': beta['id'], 'title': 'beta secret', 'state': 'todo'},
                         su, headers={'Idempotency-Key': 'beta-once'})
        assert su_replay[1].get('reused') is True, su_replay
        assert len(call(api, '/api/collections/teams/records', token=su)[1]['items']) == 2
        print('team scope: ok')
    finally:
        child.terminate()
        child.wait(timeout=10)
