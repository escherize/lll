#!/usr/bin/env python3
"""LLL-630: every request to the board that is not a GET or HEAD must carry
the board's own Origin. The lll_board cookie is SameSite=Lax, which another
port on the same host (127.0.0.1:9999) does not count as cross-site, so
without this check any local page could write as the viewer.

The routes are read from the source, not listed here: every pattern
registered on the board router that admits a non-GET method is probed, so a
route added later is covered without anyone remembering this file. Each
probe carries a valid board cookie and must get 403 from another port, with
no Origin, with Origin null and with only a Referer. The board's own page
(with or without Sec-Fetch-Site, as over plain-HTTP LAN) still writes, and
the CLI, which talks to /api/ through the same address, is unaffected. A
real browser still submits the invite name form and the sign-in confirm
page, the two forms served outside the gate."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from board_startup import wait_for_endpoints
from browser_session import new_session, open_session, require_result

binary = str(Path(sys.argv[1]).resolve())
source = Path(__file__).resolve().parent.parent / 'src' / 'serve'


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


raw = urllib.request.build_opener(NoRedirect)


def call(base, path, body=None, token='', method=None, headers=None, form=False):
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
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
    return resp.status, text


def registered_patterns():
    """Every pattern the board router registers, from the source."""
    text = '\n'.join(p.read_text() for p in sorted(source.glob('*.lis')) if not p.name.endswith('.test.lis'))
    calls = re.findall(r'\bmux\.Handle(?:Func)?\(\s*([^,]+),', text)
    literal = [c.strip()[1:-1] for c in calls if c.strip().startswith('"')]
    dynamic = [c.strip() for c in calls if not c.strip().startswith('"')]
    # The one computed registration: the disabled admin UI's 404s.
    assert dynamic == ['path'], f'a route is registered with a computed pattern; teach this test: {dynamic}'
    return literal + ['/_', '/_/']


def concrete(pattern):
    """A request path that the pattern matches."""
    path = pattern.split(' ', 1)[-1]
    fill = {'team': 'ALPHA', 'kind': 'label', 'section': 'identity', 'code': 'A' * 43, 'key': 'ALPHA-1',
            'slug': 'index', '$': ''}
    return re.sub(r'\{([^}.]+)(?:\.\.\.)?\}', lambda m: fill[m[1]], path)


with tempfile.TemporaryDirectory(prefix='lll-630-') as directory:
    root = Path(directory)
    (root / 'home').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root / 'home'), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='origin-owner', LLL_ADMIN_EMAIL='origin@example.invalid',
               LLL_ADMIN_PASSWORD='local-origin-password', LLL_BOARD_TOKEN='local-origin-board')
    log = root / 'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        endpoint = wait_for_endpoints(log)
        api, board = endpoint['db_url'], endpoint['board_url']
        su = call(api, '/api/collections/_superusers/auth-with-password',
                  {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})[1]['token']
        alpha = next(t for t in call(api, '/api/collections/teams/records', token=su)[1]['items'] if t['key'] == 'ALPHA')
        assert call(api, '/api/collections/issues/records', {'team': alpha['id'], 'title': 'target', 'state': 'todo'},
                    su)[0] == 200
        # A full member's own token is a board cookie too (LLL-545).
        rec = call(api, '/api/collections/members/records', {
            'name': 'writer', 'email': 'writer@example.test', 'password': 'pw12345678', 'passwordConfirm': 'pw12345678',
            'kind': 'person', 'scope': 'all', 'mode': 'rw'}, su)[1]
        member_tok = call(api, f"/api/collections/members/impersonate/{rec['id']}", {'duration': 3600}, su)[1]['token']

        def state():
            items = call(api, '/api/collections/issues/records?filter=(number=1)', token=su)[1]['items']
            return items[0]['state']

        unsafe = []
        for pattern in registered_patterns():
            method = pattern.split(' ', 1)[0] if ' ' in pattern else ''
            if method in ('GET', 'HEAD'):
                continue
            if pattern == '/api/':
                continue  # the exemption, checked below
            unsafe.append((method or 'POST', concrete(pattern)))
        names = {p for _, p in unsafe}
        for expected in ['/state', '/bot', '/comment', '/claim', '/labels', '/create', '/login', '/views/save',
                         '/settings/access/token', '/t/ALPHA/settings/label', '/join/' + 'A' * 43]:
            assert expected in names, f'route scan missed {expected}: {sorted(names)}'
        assert len(unsafe) >= 25, unsafe

        other = 'http://127.0.0.1:9999'
        attacks = {
            'another port, same-site': {'Origin': other, 'Sec-Fetch-Site': 'same-site'},
            'another port, no fetch metadata': {'Origin': other},
            'no Origin': {},
            'Origin null': {'Origin': 'null', 'Sec-Fetch-Site': 'cross-site'},
            'Referer only': {'Referer': board + '/t/ALPHA/'},
            'port-less host': {'Origin': 'http://127.0.0.1'},
            'method override': {'Origin': other, 'X-HTTP-Method-Override': 'GET'},
        }
        body = {'key': 'ALPHA-1', 'state': 'done', 'body': 'csrf', 'title': 'csrf', 'name': 'csrf', '_method': 'GET'}
        probes = 0
        for cookie in [env['LLL_BOARD_TOKEN'], member_tok]:
            for method, path in unsafe:
                for label, hdrs in attacks.items():
                    code, text = call(board, path, body, method=method, form=True,
                                      headers={'Cookie': 'lll_board=' + cookie, **hdrs})
                    assert code == 403, (method, path, label, code, str(text)[:200])
                    probes += 1
        assert state() == 'todo', 'a refused cross-origin request moved the issue'

        # The board's own page still writes: with Sec-Fetch-Site, and without
        # it as a browser sends to a plain-HTTP LAN board.
        own = {'Cookie': 'lll_board=' + env['LLL_BOARD_TOKEN'], 'Origin': board}
        code, text = call(board, '/state', {'key': 'ALPHA-1', 'state': 'in-progress'}, form=True,
                          headers={**own, 'Sec-Fetch-Site': 'same-origin'})
        assert code == 200 and state() == 'in-progress', (code, text)
        code, text = call(board, '/state', {'key': 'ALPHA-1', 'state': 'in-review'}, form=True, headers=own)
        assert code == 200 and state() == 'in-review', (code, text)
        code, text = call(board, '/state', {'key': 'ALPHA-1', 'state': 'todo'}, form=True,
                          headers={'Cookie': 'lll_board=' + member_tok, 'Origin': board})
        assert code == 200 and state() == 'todo', (code, text)
        # Reads and the live stream need no Origin.
        assert call(board, '/t/ALPHA/', headers={'Cookie': 'lll_board=' + member_tok})[0] == 200

        # The CLI, pointed at the board's own address (its /api/ proxy), sends
        # no Origin and keeps working; so does a raw API write from elsewhere.
        cli = dict(env, LLL_URL=board, LLL_TOKEN=member_tok, LC_ALL='C')
        out = subprocess.run([binary, 'issue', 'update', 'ALPHA-1', '--state', 'done'], cwd=root, env=cli,
                             text=True, capture_output=True, timeout=30)
        assert out.returncode == 0 and state() == 'done', out.stdout + out.stderr
        code, text = call(board, '/api/collections/issues/records', {'team': alpha['id'], 'title': 'api', 'state': 'todo'},
                          member_tok, headers={'Origin': other, 'Sec-Fetch-Site': 'same-site'})
        assert code == 200, (code, text)

        # A real browser still submits the two forms served outside the gate:
        # the sign-in confirm page and an invite's name form. Under
        # Referrer-Policy no-referrer their POSTs carried Origin: null.
        browser = 'skipped (no playwright-cli)'
        if shutil.which('playwright-cli'):
            code, minted = call(api, '/api/lll/invites', {'teams': [alpha['id']], 'mode': 'ro'}, member_tok)
            assert code == 200, minted
            script = (Path(__file__).resolve().parent / 'browser_join_login.js').read_text()
            script = script.replace('__CONFIRM_LINK__', f'{board}/t/ALPHA/?board_token={member_tok}')
            script = script.replace('__JOIN_URL__', f"{board}/join/{minted['code']}")
            session = new_session()
            try:
                open_session(session, 'about:blank')
                result = subprocess.run(['playwright-cli', '-s=' + session, 'run-code', script], text=True,
                                        capture_output=True, timeout=90)
                require_result(result, 'join and confirm passed', board)
            finally:
                subprocess.run(['playwright-cli', '-s=' + session, 'close'], capture_output=True, timeout=15)
            browser = 'browser join and sign-in confirm ok'
        print(f'board origin: {browser}; ok ({len(unsafe)} unsafe routes, {probes} refused probes)')
    finally:
        child.terminate()
        child.wait(timeout=15)
