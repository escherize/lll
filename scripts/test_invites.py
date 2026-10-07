#!/usr/bin/env python3
"""Single-use invite links (LLL-544): 'lll invite create' prints <board>/join/<code>;
redeeming it once creates a person member with exactly the invite's grants and sets
the board cookie; every other redemption is refused with the fix named."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
FIX = 'ask whoever invited you for a new link'


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


raw = urllib.request.build_opener(NoRedirect)


def call(base, path, body=None, token='', method=None, headers=None, form=False):
    """(status, parsed-or-text body, response headers). Never raises on HTTP errors."""
    hdrs = dict(headers or {})
    if body is not None:
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    if token:
        hdrs['Authorization'] = 'Bearer ' + token
    data = None if body is None else (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
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


with tempfile.TemporaryDirectory(prefix='lll-invites-') as directory:
    root = Path(directory)
    home = root / 'home'
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(home), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='invite-owner', LLL_ADMIN_EMAIL='invites@example.invalid',
               LLL_ADMIN_PASSWORD='local-invites-password', LLL_BOARD_TOKEN='local-invites-board')
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
        call(api, '/api/collections/issues/records', {'team': alpha['id'], 'title': 'alpha work', 'state': 'todo'}, su)
        call(api, '/api/collections/issues/records', {'team': beta['id'], 'title': 'beta secret', 'state': 'todo'}, su)

        def member(name, **access):
            body = {'name': name, 'email': f'{name}@example.test', 'password': 'pw12345678',
                    'passwordConfirm': 'pw12345678', 'kind': 'person', **access}
            code, rec, _ = call(api, '/api/collections/members/records', body, su)
            assert code == 200, rec
            _, a, _ = call(api, '/api/collections/members/auth-with-password',
                           {'identity': body['email'], 'password': body['password']})
            return a['token']

        owner = member('owner', scope='all', mode='rw')
        cli = dict(env, LLL_URL=api, LLL_WEB_URL=board, LLL_TOKEN=owner, LC_ALL='C')

        def lll(*argv, token=owner):
            return subprocess.run([binary, *argv], cwd=root, env=dict(cli, LLL_TOKEN=token), text=True,
                                  capture_output=True, timeout=30)

        def invite(*argv, token=owner):
            out = lll('invite', 'create', *argv, token=token)
            assert out.returncode == 0, out.stdout + out.stderr
            link = out.stdout.strip()
            assert link.startswith(board + '/join/') and len(link.rsplit('/', 1)[1]) == 43, link
            return link[len(board):]

        def redeem(path, name, headers=None):
            return call(board, path, {'name': name}, method='POST', headers=headers, form=True)

        # The form: outside the gate, and nothing about it leaks the code.
        path = invite('--team', 'ALPHA', '--ro')
        code, page, headers = call(board, path)
        assert code == 200 and "<form method='post'" in page, page
        assert headers['Referrer-Policy'] == 'no-referrer' and headers['Cache-Control'] == 'no-store', headers
        assert "frame-ancestors 'none'" in headers['Content-Security-Policy'], headers

        # Another site cannot submit the form, and trying does not spend the code.
        code, page, headers = redeem(path, 'csrf', {'Sec-Fetch-Site': 'cross-site', 'Origin': 'https://evil.example'})
        assert code == 403 and 'Set-Cookie' not in headers, (code, headers)
        # A name the redeemer may not take keeps the code alive too.
        for taken in ['owner', 'OWNER', 'bot-me', '<b>x</b>']:
            code, page, headers = redeem(path, taken)
            assert code == 400 and "<form method='post'" in page and 'Set-Cookie' not in headers, (taken, code, page)

        # Redeeming once works: a 303 that names a team page, never the code.
        code, _, headers = redeem(path, 'Ada Reader')
        assert code == 303 and headers['Location'] == '/t/ALPHA/', (code, dict(headers))
        assert path.rsplit('/', 1)[1] not in headers['Location']
        cookie = headers['Set-Cookie']
        for attr in ['lll_board=', 'Path=/', 'Max-Age=31536000', 'HttpOnly', 'SameSite=Lax']:
            assert attr in cookie, cookie
        token = cookie.split('lll_board=', 1)[1].split(';', 1)[0]

        # The member holds exactly the invite's grants and nothing it chose.
        rec = next(m for m in call(api, '/api/collections/members/records?perPage=200', token=su)[1]['items']
                   if m['name'] == 'Ada Reader')
        assert (rec['kind'], rec['owner'], rec['scope'], rec['teams'], rec['mode']) == \
            ('person', '', 'teams', [alpha['id']], 'ro'), rec
        # Its token reads ALPHA and nothing of BETA, and cannot write.
        assert [t['key'] for t in call(api, '/api/collections/teams/records', token=token)[1]['items']] == ['ALPHA']
        assert [i['title'] for i in call(api, '/api/collections/issues/records', token=token)[1]['items']] == ['alpha work']
        assert call(api, '/api/collections/issues/records', {'team': alpha['id'], 'title': 'x', 'state': 'todo'},
                    token)[0] == 403

        # A second redemption, an unknown code and an expired code are refused, naming the fix.
        code, page, headers = redeem(path, 'Second Person')
        assert code == 410 and 'already been used' in page and FIX in page.lower(), (code, page)
        assert 'Set-Cookie' not in headers and "<form method='post'" not in page
        code, page, _ = redeem('/join/' + 'A' * 43, 'Nobody')
        assert code == 404 and FIX in page.lower(), (code, page)
        stale = invite('--team', 'ALPHA')
        listed = call(api, '/api/collections/invites/records?sort=-created&perPage=1', token=su)[1]['items'][0]
        assert stale.rsplit('/', 1)[1] not in json.dumps(listed), 'the invite stored its code'
        call(api, f"/api/collections/invites/records/{listed['id']}", {'expires': '2020-01-01 00:00:00.000Z'}, su,
             method='PATCH')
        code, page, _ = redeem(stale, 'Late Person')
        assert code == 410 and 'expired' in page and FIX in page.lower(), (code, page)
        assert not any(m['name'] in ('Second Person', 'Nobody', 'Late Person')
                       for m in call(api, '/api/collections/members/records?perPage=200', token=su)[1]['items'])

        # An invite cannot grant more than its creator holds.
        guest = member('guest', scope='teams', teams=[alpha['id']], mode='rw')
        reader = member('reader', scope='teams', teams=[alpha['id']], mode='ro')
        out = lll('invite', 'create', '--team', 'ALPHA', '--ro', token=reader)
        assert out.returncode != 0 and 'cannot invite anyone' in out.stderr, out.stdout + out.stderr
        code, body, _ = call(api, '/api/lll/invites', {'teams': [beta['id']], 'mode': 'ro'}, guest)
        assert code == 400 and 'that you can see' in body['message'], body
        code, body, _ = call(api, '/api/lll/invites', {'teams': [alpha['id'], beta['id']], 'mode': 'ro'}, guest)
        assert code == 400, body
        code, body, _ = call(api, '/api/lll/invites', {'teams': [], 'mode': 'rw'}, owner)
        assert code == 400, body
        # The name rule holds after joining too: a member renaming itself
        # through the API gets the redeemer's rule. Its other fields stay editable.
        me = rec_id = next(m for m in call(api, '/api/collections/members/records?perPage=200', token=su)[1]['items']
                           if m['name'] == 'Ada Reader')['id']
        for bad in ['bot-evil', 'Ｓcratch', 'OWNER', 'Owner', '<img src=x onerror=alert(1)>', 'Ada  Reader', 'Ada.']:
            code, body, _ = call(api, f'/api/collections/members/records/{me}', {'name': bad}, token, method='PATCH')
            assert code == 400, (bad, code, body)
        assert call(api, f'/api/collections/members/records/{me}', {'name': 'Ada Reader'}, token, method='PATCH')[0] == 200
        assert call(api, f'/api/collections/members/records/{me}', {'name': 'ada reader'}, token, method='PATCH')[0] == 200
        assert call(api, f'/api/collections/members/records/{me}', {'name': 'Ada R'}, token, method='PATCH')[0] == 200
        # A superuser is not held to it (existing names predate the rule).
        assert call(api, f'/api/collections/members/records/{rec_id}', {'name': 'Ada R.'}, su, method='PATCH')[0] == 200
        assert call(api, f'/api/collections/members/records/{me}', {'emailVisibility': False}, token,
                    method='PATCH')[0] == 200
        # A member with an owner does not invite people, bot or person.
        code, ownedp, _ = call(api, '/api/collections/members/records', {
            'name': 'ownedp', 'email': 'ownedp@example.test', 'password': 'pw12345678', 'passwordConfirm': 'pw12345678',
            'kind': 'person', 'owner': next(m for m in call(api, '/api/collections/members/records?perPage=200',
                                                            token=su)[1]['items'] if m['name'] == 'owner')['id'],
            'scope': 'teams', 'teams': [alpha['id']], 'mode': 'rw'}, su)
        assert code == 200, ownedp
        ownedp_tok = call(api, '/api/collections/members/auth-with-password',
                          {'identity': 'ownedp@example.test', 'password': 'pw12345678'})[1]['token']
        code, body, _ = call(api, '/api/lll/invites', {'teams': [alpha['id']], 'mode': 'rw'}, ownedp_tok)
        assert code == 403 and 'owned members cannot invite' in body['message'].lower(), body
        # A bot does not invite people, even one owned by a full member.
        out = lll('bot', 'bot-inviter')
        assert out.returncode == 0, out.stdout + out.stderr
        bot = next(l for l in out.stdout.splitlines() if l.startswith('LLL_TOKEN='))[len('LLL_TOKEN='):]
        code, body, _ = call(api, '/api/lll/invites', {'teams': [alpha['id']], 'mode': 'ro'}, bot)
        assert code == 403 and 'bots and owned members cannot invite' in body['message'].lower(), body
        rw = invite('--team', 'ALPHA', token=guest)
        code, _, headers = redeem(rw, 'Rae Writer')
        assert code == 303, code
        rae = headers['Set-Cookie'].split('lll_board=', 1)[1].split(';', 1)[0]
        rec = next(m for m in call(api, '/api/collections/members/records?perPage=200', token=su)[1]['items']
                   if m['name'] == 'Rae Writer')
        assert (rec['scope'], rec['teams'], rec['mode']) == ('teams', [alpha['id']], 'rw'), rec

        # A joined rw member may create a bot it owns, under the same name rule,
        # so it cannot impersonate an existing bot ('bot-inviter') in attribution.
        def own_bot(name, token=rae, owner=rec['id']):
            return call(api, '/api/collections/members/records', {
                'name': name, 'kind': 'bot', 'owner': owner, 'email': f'b{len(name)}{abs(hash(name))}@example.test',
                'password': 'pw12345678', 'passwordConfirm': 'pw12345678'}, token)
        for bad in ['bot-Inviter', 'bot-ｉnviter', 'bot-inviter​', 'bot-<img src=x onerror=alert(1)>',
                    'bot-' + 'a' * 300, 'bot-x\x1b[2J\nsecond line']:
            code, body, _ = own_bot(bad)
            assert code == 400, (bad, code, body)
        code, body, _ = own_bot('bot-rae-helper')
        assert code == 200 and body['owner'] == rec['id'], body
        out = lll('bot', 'bot-rae-cli', token=rae)
        assert out.returncode == 0, out.stdout + out.stderr
        # A superuser is not held to it.
        code, body, _ = own_bot('bot-Rae.', su)
        assert code == 200, body

        # The invites collection answers no member token: list, view, filter, create.
        for tok in [owner, guest, token]:
            assert call(api, '/api/collections/invites/records', token=tok)[0] == 403
            assert call(api, f"/api/collections/invites/records/{listed['id']}", token=tok)[0] == 403
            assert call(api, "/api/collections/members/records?filter=@collection.invites.mode='ro'", token=tok)[0] == 403
            assert call(api, "/api/collections/members/records?filter=invites_via_redeemed_by.mode='ro'",
                        token=tok)[0] == 400
            assert call(api, '/api/collections/invites/records', {'code_hash': 'a' * 64, 'mode': 'rw'}, tok)[0] == 403
        # Control: a superuser does see them, so the 403s above are the rules.
        assert call(api, '/api/collections/invites/records', token=su)[1]['totalItems'] == 3
        print('invites: ok')
    finally:
        child.terminate()
        child.wait(timeout=10)
