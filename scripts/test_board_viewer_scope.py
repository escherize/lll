#!/usr/bin/env python3
"""LLL-545: a member token in the board cookie scopes the board to the
member's teams. Pages, search, raw markdown and the live stream carry no key,
name or issue of a hidden team; writes run as the viewer; a read-only viewer
cannot write; a bot's cookie is capped by its owner; the board token is
unchanged."""
import hashlib
import hmac
import json
import re
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())

# Markers that only the hidden team carries: its key, its name, its issue
# title, a word in its doc and a comment on its issue.
HIDDEN = ['BETA', 'Bravo Hidden Team', 'zebra hidden plan', 'zebradoc', 'zebra comment']


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


raw = urllib.request.build_opener(NoRedirect)


def call(base, path, body=None, token='', method=None, headers=None, form=False):
    """(status, parsed-or-text body, headers). Never raises on HTTP errors."""
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
    return resp.status, text, resp.headers


def assert_clean(text, where):
    for marker in HIDDEN:
        assert marker not in text, f'{where} leaked {marker!r}'


with tempfile.TemporaryDirectory(prefix='lll-545-') as directory:
    root = Path(directory)
    (root / 'home').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root / 'home'), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='board-owner', LLL_ADMIN_EMAIL='scope@example.invalid',
               LLL_ADMIN_PASSWORD='local-viewer-scope-password', LLL_BOARD_TOKEN='local-viewer-scope-board')
    log = root / 'up.log'
    streams = []
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        endpoint = wait_for_endpoints(log)
        api, board = endpoint['db_url'], endpoint['board_url']
        _, su, _ = call(api, '/api/collections/_superusers/auth-with-password',
                        {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})
        su = su['token']
        alpha = next(t for t in call(api, '/api/collections/teams/records', token=su)[1]['items'] if t['key'] == 'ALPHA')
        _, beta, _ = call(api, '/api/collections/teams/records', {'key': 'BETA', 'name': 'Bravo Hidden Team'}, su)

        def issue(team, title):
            code, rec, _ = call(api, '/api/collections/issues/records', {'team': team['id'], 'title': title, 'state': 'todo'}, su)
            assert code == 200, rec
            return rec

        ia = issue(alpha, 'alpha work')
        ib = issue(beta, 'zebra hidden plan')
        call(api, '/api/collections/comments/records', {'issue': ib['id'], 'body': 'zebra comment'}, su)
        call(api, '/api/collections/docs/records', {'team': beta['id'], 'slug': 'bdoc', 'title': 'zebradoc',
                                                    'kind': 'note', 'body': 'zebradoc body'}, su)
        # An all-scope writer may link across teams; the scoped page must not show it.
        code, _, _ = call(api, '/api/collections/docs/records', {'team': alpha['id'], 'slug': 'cross', 'title': 'cross',
                                                                 'kind': 'note', 'body': 'b', 'issues': [ia['id'], ib['id']]}, su)
        assert code == 200

        def member(name, **access):
            body = {'name': name, 'email': f'{name}@example.test', 'password': 'pw12345678',
                    'passwordConfirm': 'pw12345678', 'kind': 'person', **access}
            code, rec, _ = call(api, '/api/collections/members/records', body, su)
            assert code == 200, rec
            code, tok, _ = call(api, f"/api/collections/members/impersonate/{rec['id']}", {'duration': 3600}, su)
            assert code == 200, tok
            return rec, tok['token']

        rw_rec, rw_tok = member('writer', scope='teams', teams=[alpha['id']], mode='rw')
        ro_rec, ro_tok = member('reader', scope='teams', teams=[alpha['id']], mode='ro')
        both_rec, both_tok = member('boss', scope='teams', teams=[alpha['id'], beta['id']], mode='rw')

        def as_cookie(tok):
            return {'Cookie': 'lll_board=' + tok}

        def page(path, tok, body=None, method=None):
            return call(board, path, body, method=method, headers=as_cookie(tok), form=body is not None)

        # --- reads: ALPHA renders, BETA answers like a missing team ---
        for tok in [rw_tok, ro_tok]:
            code, body, _ = page('/t/ALPHA/', tok)
            assert code == 200 and 'alpha work' in body, (code, body[:300])
            assert_clean(body, 'scoped board page')
            # The rail offers nothing a scoped viewer cannot open.
            for absent in ['id="rail-favorites"', 'id="rail-views"', '/t/ALPHA/settings']:
                assert absent not in body, f'scoped rail shows {absent}'
            for path in ['/t/ALPHA/issues', '/t/ALPHA/projects', '/t/ALPHA/issue/ALPHA-1', '/t/ALPHA/doc/cross',
                         '/t/ALPHA/?raw', '/t/ALPHA/issues?raw', '/t/ALPHA/issue/ALPHA-1?raw', '/t/ALPHA/doc/cross?raw']:
                code, body, _ = page(path, tok)
                assert code == 200, (path, code, body)
                assert_clean(body, path)
        missing = page('/t/NOPE/', rw_tok)
        for path in ['/t/BETA/', '/t/BETA', '/t/beta/issues', '/t/BETA/issue/BETA-1', '/t/ALPHA/issue/BETA-1',
                     '/t/BETA/doc/bdoc', '/t/BETA/search?q=zebra', '/events?team=BETA', '/events?page=issue&key=BETA-1',
                     '/attachments/file?key=BETA-1&file=x.png', '/issue/BETA-1']:
            code, body, _ = page(path, rw_tok)
            assert code == 404, (path, code)
            assert 'Bravo' not in str(body) and 'zebra' not in str(body), (path, body)
        hidden_body = page('/t/BETA/', rw_tok)[1].replace('BETA', 'NOPE')
        assert hidden_body == missing[1] and missing[0] == 404, 'a hidden team answers differently from a missing one'
        for path in ['/t/ALPHA/settings/identity', '/t/ALPHA/settings/access', '/search?q=zebra']:
            assert page(path, rw_tok)[0] == 403, path
        assert page('/', rw_tok)[0] == 303 and page('/', rw_tok)[2]['Location'] == '/t/ALPHA/'

        # --- the hrefs the board renders open for a scoped viewer ---
        board_html = page('/t/ALPHA/', rw_tok)[1]
        card = re.search(r'class="card" id="issue-[^"]+" href="(/issue/ALPHA-\d+)"', board_html)
        assert card, 'no card href on the scoped board'
        code, _, headers = page(card.group(1), rw_tok)
        assert code == 303 and headers['Location'].startswith('/t/ALPHA/issue/ALPHA-'), (code, dict(headers))
        assert page(headers['Location'], rw_tok)[0] == 200
        doc_link = re.search(r'href="(/issue/ALPHA-\d+)"', page('/t/ALPHA/doc/cross', rw_tok)[1]).group(1)
        assert page(doc_link, rw_tok)[0] == 303

        # --- search: the hidden team's words find nothing ---
        for path in ['/t/ALPHA/search?q=zebra', '/t/ALPHA/search?q=zebra&raw', '/t/ALPHA/search?q=zebra&palette=1',
                     '/t/ALPHA/search?q=zebra&fragment=1']:
            code, body, _ = page(path, rw_tok)
            assert code == 200, (path, code)
            assert_clean(body, path)
        assert 'alpha work' in page('/t/ALPHA/search?q=alpha&raw', rw_tok)[1], 'control: search works for the scoped viewer'

        # --- the live stream: an ALPHA event arrives, a BETA event never does ---
        def stream(path, tok, name):
            out = root / f'{name}.log'
            handle = out.open('w')
            proc = subprocess.Popen(['curl', '-sN', '-H', f'Cookie: lll_board={tok}', board + path],
                                    stdout=handle, stderr=subprocess.DEVNULL, start_new_session=True)
            streams.append(proc)
            return out

        def wait_for(out, needle):
            deadline = time.monotonic() + 15
            while needle not in out.read_text() and time.monotonic() < deadline:
                time.sleep(.1)
            assert needle in out.read_text(), f'{out.name}: never saw {needle!r}'

        scoped_board = stream('/events?team=ALPHA', rw_tok, 'scoped-board')
        scoped_issue = stream('/events?page=issue&key=ALPHA-1', rw_tok, 'scoped-issue')
        full_beta = stream('/events?team=BETA', env['LLL_BOARD_TOKEN'], 'full-beta')
        wait_for(scoped_board, 'alpha work')
        wait_for(scoped_issue, 'alpha work')
        wait_for(full_beta, 'zebra hidden plan')
        # BETA changes first; the bridge is serial, so once ALPHA's change has
        # arrived any BETA fragment bound for this client would have too.
        call(api, f"/api/collections/issues/records/{ib['id']}", {'title': 'zebra hidden plan two'}, su, 'PATCH')
        call(api, '/api/collections/comments/records', {'issue': ib['id'], 'body': 'zebra comment two'}, su)
        call(api, f"/api/collections/issues/records/{ia['id']}", {'title': 'alpha moved'}, su, 'PATCH')
        wait_for(full_beta, 'zebra hidden plan two')
        wait_for(scoped_board, 'alpha moved')
        wait_for(scoped_issue, 'alpha moved')
        time.sleep(.5)
        assert_clean(scoped_board.read_text(), 'scoped board stream')
        assert_clean(scoped_issue.read_text(), 'scoped issue stream')

        # --- writes: attributed to the viewer, kept inside its teams ---
        def flash(path, tok, body):
            code, text, _ = page(path, tok, body)
            return code, text

        code, text = flash('/title', rw_tok, {'key': 'ALPHA-1', 'title': 'alpha by writer'})
        assert code == 200 and ' hidden role="alert"' in text, text
        assert call(api, f"/api/collections/issues/records/{ia['id']}", token=su)[1]['title'] == 'alpha by writer'
        flash('/comment', rw_tok, {'key': 'ALPHA-1', 'body': 'written by the viewer'})
        comments = call(api, '/api/collections/comments/records?perPage=200', token=su)[1]['items']
        assert next(c for c in comments if c['body'] == 'written by the viewer')['author'] == rw_rec['id']
        flash('/create', rw_tok, {'team': 'ALPHA', 'title': 'created by the viewer'})
        made = call(api, '/api/collections/issues/records?perPage=200', token=su)[1]['items']
        assert next(i for i in made if i['title'] == 'created by the viewer')['creator'] == rw_rec['id']
        flash('/claim', rw_tok, {'key': 'ALPHA-1', 'member_id': 'whatever-the-button-said'})
        claims = call(api, '/api/collections/claims/records', token=su)[1]['items']
        assert [c['member'] for c in claims if c['issue'] == ia['id']] == [rw_rec['id']], claims
        # Another team's issue answers like a missing one, and nothing changes.
        code, text = flash('/title', rw_tok, {'key': 'BETA-1', 'title': 'hijacked'})
        assert 'issue BETA-1 not found' in text, text
        code, text = flash('/comment', rw_tok, {'key': 'BETA-1', 'body': 'hijacked'})
        assert 'issue BETA-1 not found' in text, text
        code, text = flash('/create', rw_tok, {'team': 'BETA', 'title': 'hijacked'})
        assert "BETA" in text and 'hijacked' not in json.dumps(call(api, '/api/collections/issues/records?perPage=200', token=su)[1])
        code, text = flash('/create', rw_tok, {'title': 'no team named'})
        assert 'no team named' not in json.dumps(call(api, '/api/collections/issues/records?perPage=200', token=su)[1]), \
            'a scoped create without a team landed in the boot team'
        assert call(api, f"/api/collections/issues/records/{ib['id']}", token=su)[1]['title'] == 'zebra hidden plan two'
        # Workspace-wide and settings writes stay closed even to a writer.
        for path in ['/favorite', '/views/save', '/settings/label', '/t/ALPHA/settings/label', '/settings/access/token']:
            assert flash(path, rw_tok, {'key': 'ALPHA-1', 'on': 'true', 'name': 'x', 'query': ''})[0] == 403, path

        # --- a read-only viewer cannot write ---
        for path in ['/title', '/comment', '/create', '/state', '/claim']:
            code, _ = flash(path, ro_tok, {'key': 'ALPHA-1', 'title': 'ro', 'body': 'ro', 'team': 'ALPHA', 'state': 'done'})
            assert code == 403, (path, code)
        assert call(api, f"/api/collections/issues/records/{ia['id']}", token=su)[1]['title'] == 'alpha by writer'
        assert 'Claim as writer' in page('/t/ALPHA/issue/ALPHA-2', rw_tok)[1], 'rw viewer is not offered its own claim'
        assert 'Claim as' not in page('/t/ALPHA/issue/ALPHA-2', ro_tok)[1], 'ro viewer offered a claim button'

        # --- two teams: both open; narrowing applies on the next request ---
        assert page('/t/BETA/', both_tok)[0] == 200 and 'zebra hidden plan two' in page('/t/BETA/', both_tok)[1]
        assert 'BETA' in page('/t/ALPHA/', both_tok)[1], 'control: the rail lists a granted second team'
        call(api, f"/api/collections/members/records/{both_rec['id']}", {'teams': [alpha['id']]}, su, 'PATCH')
        assert page('/t/BETA/', both_tok)[0] == 404, 'narrowing was not read on the next request'

        # --- a bot's cookie is capped by its owner ---
        owner_rec, _ = member('owner', scope='teams', teams=[alpha['id'], beta['id']], mode='rw')
        code, bot, _ = call(api, '/api/collections/members/records',
                            {'name': 'bot-owned', 'email': 'bot@example.test', 'password': 'pw12345678',
                             'passwordConfirm': 'pw12345678', 'kind': 'bot', 'owner': owner_rec['id'],
                             'scope': 'teams', 'teams': [alpha['id'], beta['id']], 'mode': 'rw'}, su)
        assert code == 200, bot
        bot_tok = call(api, f"/api/collections/members/impersonate/{bot['id']}", {'duration': 3600}, su)[1]['token']
        assert page('/t/BETA/', bot_tok)[0] == 200, 'control: the bot sees both teams'
        call(api, f"/api/collections/members/records/{owner_rec['id']}", {'teams': [alpha['id']], 'mode': 'ro'}, su, 'PATCH')
        assert page('/t/BETA/', bot_tok)[0] == 404, 'a bot cookie outlived its owner\'s narrowing'
        assert page('/t/ALPHA/', bot_tok)[0] == 200
        assert flash('/title', bot_tok, {'key': 'ALPHA-1', 'title': 'bot'})[0] == 403, 'bot wrote past its read-only owner'

        # --- credentials that are not a member's are refused ---
        for bad in [su, 'not-a-token', rw_tok[:-3] + 'abc']:
            assert page('/t/ALPHA/', bad)[0] == 401, bad[:12]
        call(api, f"/api/collections/members/records/{ro_rec['id']}", token=su, method='DELETE')
        assert page('/t/ALPHA/', ro_tok)[0] == 401, 'a deleted member\'s cookie still opens the board'

        # --- login by query: the member token becomes a year-long cookie ---
        direct = {'Sec-Fetch-Site': 'none'}
        code, _, headers = call(board, f'/t/ALPHA/?board_token={rw_tok}', headers=direct)
        assert code == 303 and headers['Location'] == '/t/ALPHA/', (code, headers)
        cookie = headers['Set-Cookie']
        assert cookie.startswith(f'lll_board={rw_tok};') and 'Max-Age=31536000' in cookie and 'HttpOnly' in cookie, cookie
        code, _, headers = call(board, f'/t/ALPHA/?board_token={both_tok}', headers={'Sec-Fetch-Site': 'same-origin'})
        assert code == 303 and 'Set-Cookie' in headers, 'control: a same-origin navigation signs in'
        # Login CSRF: a link carrying another member's token must not swap a
        # signed-in browser's identity.
        code, _, headers = call(board, f'/t/ALPHA/?board_token={both_tok}', headers=dict(as_cookie(rw_tok), **direct))
        assert code == 303 and 'Set-Cookie' not in headers, (code, dict(headers))
        # Without positive evidence (cross-site, or no header at all, which is
        # what browsers send to a plain-HTTP LAN board) a link sets nothing
        # and shows a confirm page that POSTs to /login.
        link = 'ALPHA.' + hmac.new(env['LLL_BOARD_TOKEN'].encode(), b'ALPHA', hashlib.sha256).hexdigest()
        for tok, hdrs, what in [(both_tok, {}, 'no header, no cookie'),
                                (both_tok, {'Sec-Fetch-Site': 'cross-site'}, 'cross-site member token'),
                                (both_tok, dict(as_cookie('expired.garbage.cookie')), 'no header, dead cookie'),
                                (link, {'Sec-Fetch-Site': 'cross-site'}, 'cross-site KEY.MAC link'),
                                (link, {}, 'KEY.MAC link, no header')]:
            code, body, headers = call(board, f'/t/ALPHA/?board_token={tok}', headers=hdrs)
            assert code == 200 and 'Set-Cookie' not in headers, (what, code, dict(headers))
            assert "action='/login'" in body and headers['Cache-Control'] == 'no-store', what
            assert "frame-ancestors 'none'" in headers['Content-Security-Policy'], what
            assert headers['Referrer-Policy'] == 'no-referrer', what
        # /login sets the cookie only for a POST from the board's own origin.
        login = {'board_token': both_tok, 'next': '/t/ALPHA/'}
        for hdrs, what in [({}, 'no Origin'), ({'Origin': 'http://evil.example'}, 'Origin mismatch'),
                           ({'Origin': board.replace('127.0.0.1', 'localhost')}, 'other host, same machine'),
                           ({'Origin': board, 'Sec-Fetch-Site': 'cross-site'}, 'browser says cross-site')]:
            code, _, headers = call(board, '/login', login, headers=hdrs, form=True)
            assert code == 403 and 'Set-Cookie' not in headers, (what, code, dict(headers))
        code, _, headers = call(board, '/login', login, headers={'Origin': board}, form=True)
        assert code == 303 and headers['Location'] == '/t/ALPHA/', (code, dict(headers))
        assert headers['Set-Cookie'].startswith(f'lll_board={both_tok};') and 'Max-Age=31536000' in headers['Set-Cookie']
        code, _, headers = call(board, '/login', {'board_token': link, 'next': '//evil.example/'},
                                headers={'Origin': board, 'Sec-Fetch-Site': 'same-origin'}, form=True)
        assert code == 303 and headers['Location'] == '/' and headers['Set-Cookie'].startswith(f'lll_board={link};'), dict(headers)
        # The confirm step keeps the cookie-replace rule.
        code, _, headers = call(board, '/login', login, headers=dict(as_cookie(rw_tok), Origin=board), form=True)
        assert code == 303 and 'Set-Cookie' not in headers, 'a /login POST replaced a signed-in cookie'
        code, _, headers = call(board, '/login', {'board_token': 'nope', 'next': '/'}, headers={'Origin': board}, form=True)
        assert code == 401 and 'Set-Cookie' not in headers
        # The board-token login is unchanged, cookie or not.
        code, _, headers = call(board, f"/t/ALPHA/?board_token={env['LLL_BOARD_TOKEN']}", headers=as_cookie(rw_tok))
        assert code == 303 and headers['Set-Cookie'].startswith(f"lll_board={env['LLL_BOARD_TOKEN']};"), dict(headers)

        # --- revocation reaches open streams (LLL-626) ---
        narrowed_rec, narrowed_tok = member('narrowed', scope='teams', teams=[alpha['id']], mode='rw')
        doomed_rec, doomed_tok = member('doomed', scope='teams', teams=[alpha['id']], mode='ro')
        narrowed_stream = stream('/events?team=ALPHA', narrowed_tok, 'narrowed')
        doomed_stream = stream('/events?page=issue&key=ALPHA-1', doomed_tok, 'doomed')
        full_alpha = stream('/events?team=ALPHA', env['LLL_BOARD_TOKEN'], 'full-alpha')
        for out in [narrowed_stream, doomed_stream, full_alpha]:
            wait_for(out, 'alpha by writer')
        revoked_procs = streams[-3:-1]
        call(api, f"/api/collections/members/records/{narrowed_rec['id']}", {'teams': [beta['id']]}, su, 'PATCH')
        call(api, f"/api/collections/members/records/{doomed_rec['id']}", token=su, method='DELETE')
        issue(alpha, 'AFTERREVOKE alpha')
        call(api, f"/api/collections/issues/records/{ia['id']}", {'title': 'AFTERREVOKE title'}, su, 'PATCH')
        wait_for(full_alpha, 'AFTERREVOKE alpha')
        wait_for(full_alpha, 'AFTERREVOKE title')
        deadline = time.monotonic() + 20
        while any(p.poll() is None for p in revoked_procs) and time.monotonic() < deadline:
            time.sleep(.2)
        assert all(p.poll() is not None for p in revoked_procs), 'a revoked stream stayed open'
        for out in [narrowed_stream, doomed_stream]:
            assert 'AFTERREVOKE' not in out.read_text(), f'{out.name} received an event after revocation'
        # An idle stream closes on the timer, with no event to trigger it.
        idle_rec, idle_tok = member('idle', scope='teams', teams=[alpha['id']], mode='ro')
        idle_stream = stream('/events?team=ALPHA', idle_tok, 'idle')
        wait_for(idle_stream, 'AFTERREVOKE alpha')
        idle_proc = streams[-1]
        call(api, f"/api/collections/members/records/{idle_rec['id']}", token=su, method='DELETE')
        deadline = time.monotonic() + 20
        while idle_proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.2)
        assert idle_proc.poll() is not None, 'an idle revoked stream stayed open past the re-check interval'

        # --- an all-scope member hangs a hidden team's label and project on
        # an ALPHA issue: no scoped surface may name them ---
        _, zeta, _ = call(api, '/api/collections/teams/records', {'key': 'ZETA', 'name': 'Zeta Hidden'}, su)
        _, zlabel, _ = call(api, '/api/collections/labels/records', {'team': zeta['id'], 'name': 'zlabelhidden'}, su)
        _, zproj, _ = call(api, '/api/collections/projects/records',
                           {'team': zeta['id'], 'name': 'zprojhidden', 'status': 'planned'}, su)
        _, alabel, _ = call(api, '/api/collections/labels/records', {'team': alpha['id'], 'name': 'alabelown'}, su)
        wide_rec, wide_tok = member('wide', scope='all', mode='rw')
        zref = ['zlabelhidden', 'zprojhidden', 'Zeta Hidden', 'ZETA']
        rw2_rec, rw2_tok = member('zviewer', scope='teams', teams=[alpha['id']], mode='rw')
        viewers = {'member': rw2_tok, 'link': link}
        zstreams = {name: (stream('/events?team=ALPHA', tok, f'z-board-{name}'),
                           stream('/events?page=issue&key=ALPHA-1', tok, f'z-issue-{name}'))
                    for name, tok in viewers.items()}
        zfull = stream('/events?page=issue&key=ALPHA-1', env['LLL_BOARD_TOKEN'], 'z-issue-full')
        zfull_board = stream('/events?team=ALPHA', env['LLL_BOARD_TOKEN'], 'z-board-full')
        for outs in list(zstreams.values()) + [(zfull, zfull_board)]:
            for out in outs:
                wait_for(out, 'AFTERREVOKE title')
        code, body, _ = call(api, f"/api/collections/issues/records/{ia['id']}",
                             {'labels': [zlabel['id'], alabel['id']], 'project': zproj['id'], 'title': 'ZREF title'},
                             wide_tok, 'PATCH')
        assert code == 200, body
        wait_for(zfull_board, 'zlabelhidden')  # control: board cards name labels
        wait_for(zfull, 'zprojhidden')  # control: the issue detail names the project
        for name, outs in zstreams.items():
            for out in outs:
                wait_for(out, 'ZREF title')
                wait_for(out, 'alabelown')
        time.sleep(.5)
        for name, outs in zstreams.items():
            for out in outs:
                text = out.read_text()
                for marker in zref:
                    assert marker not in text, f'{out.name} leaked {marker}'
        for name, tok in viewers.items():
            paths = ['/t/ALPHA/', '/t/ALPHA/?raw', '/t/ALPHA/issues', '/t/ALPHA/issues?raw',
                     '/t/ALPHA/issue/ALPHA-1', '/t/ALPHA/issue/ALPHA-1?raw',
                     '/t/ALPHA/search?q=ZREF', '/t/ALPHA/search?q=ZREF&raw', '/t/ALPHA/search?q=ZREF&fragment=1',
                     '/t/ALPHA/search?q=ZREF&palette=1']
            for path in paths:
                code, body, _ = page(path, tok)
                assert code == 200 and 'ZREF title' in body, (name, path, code)
                for marker in zref:
                    assert marker not in body, f'{name} {path} leaked {marker}'
            # Searching the hidden label's name must not find the issue.
            assert 'ZREF title' not in page('/t/ALPHA/search?q=zlabelhidden&raw', tok)[1], name
        # A rejected property edit re-renders the property panel as the board's member.
        code, text = flash('/project', rw2_tok, {'key': 'ALPHA-1', 'project': 'bogus', 'property_edit': '1'})
        assert 'issue-properties' in text and 'alabelown' in text, text[:400]
        for marker in zref:
            assert marker not in text, f'property recovery leaked {marker}'
        code, text = flash('/title', rw2_tok, {'key': 'BETA-1', 'title': 'x', 'property_edit': '1'})
        assert 'issue BETA-1 not found' in text and 'zebra' not in text and 'Bravo' not in text, text[:400]
        # Controls: the board token still sees both names.
        full_issue = page('/t/ALPHA/issue/ALPHA-1', env['LLL_BOARD_TOKEN'])[1]
        assert 'zprojhidden' in full_issue, 'control: board token lost the project'
        assert 'zlabelhidden' in page('/t/ALPHA/', env['LLL_BOARD_TOKEN'])[1], 'control: board token lost the label'

        # --- the board token is unchanged ---
        full = env['LLL_BOARD_TOKEN']
        code, body, _ = page('/t/BETA/', full)
        assert code == 200 and 'zebra hidden plan two' in body
        assert 'BETA' in page('/t/ALPHA/', full)[1] and 'BETA-1' in page('/t/ALPHA/doc/cross?raw', full)[1]
        assert page('/t/ALPHA/settings/identity', full)[0] == 200
        full_rail = page('/t/ALPHA/', full)[1]
        for present in ['id="rail-favorites"', 'id="rail-views"', '/t/ALPHA/settings']:
            assert present in full_rail, f'control: board-token rail lost {present}'
    finally:
        for proc in streams:
            proc.terminate()
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
print('board viewer scope: ok')
