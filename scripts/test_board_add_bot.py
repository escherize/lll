#!/usr/bin/env python3
"""LLL-546: the board's "Add a bot". A read-write member viewer mints a bot
it owns, with its own token, and gets the agent prompt once in that POST's
response. Pasted into a fresh shell, the prompt lists the owner's teams only.
The token never appears again: not on a reload, not on the live stream, not
in the server log. Read-only, team-link, board-token and bot viewers cannot
mint, and a viewer cannot mint for a team it cannot see."""
import html
import json
import os
from pathlib import Path
import re
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


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


raw = urllib.request.build_opener(NoRedirect)


LAST_HEADERS = [None]


def call(base, path, body=None, token='', method=None, headers=None, form=False):
    """(status, parsed-or-text body). Never raises on HTTP errors."""
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
    LAST_HEADERS[:] = [resp.headers]
    try:
        text = json.loads(text)
    except ValueError:
        pass
    return resp.status, text


TOKEN = re.compile(r'export LLL_TOKEN=([A-Za-z0-9._-]+)')

with tempfile.TemporaryDirectory(prefix='lll-546-') as directory:
    root = Path(directory)
    (root / 'home').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root / 'home'), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='board-owner', LLL_ADMIN_EMAIL='bot@example.invalid',
               LLL_ADMIN_PASSWORD='local-add-bot-password', LLL_BOARD_TOKEN='local-add-bot-board')
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
        beta = call(api, '/api/collections/teams/records', {'key': 'BETA', 'name': 'Beta'}, su)[1]
        for team, title in [(alpha, 'alpha work'), (beta, 'beta secret')]:
            assert call(api, '/api/collections/issues/records', {'team': team['id'], 'title': title, 'state': 'todo'}, su)[0] == 200

        def member(name, **access):
            body = {'name': name, 'email': f'{name}@example.test', 'password': 'pw12345678',
                    'passwordConfirm': 'pw12345678', 'kind': 'person', **access}
            code, rec = call(api, '/api/collections/members/records', body, su)
            assert code == 200, rec
            return rec, call(api, f"/api/collections/members/impersonate/{rec['id']}", {'duration': 3600}, su)[1]['token']

        def members():
            return {m['name']: m for m in call(api, '/api/collections/members/records?perPage=200', token=su)[1]['items']}

        writer, rw_tok = member('writer', scope='teams', teams=[alpha['id']], mode='rw')
        _, ro_tok = member('reader', scope='teams', teams=[alpha['id']], mode='ro')
        full = env['LLL_BOARD_TOKEN']

        def page(path, tok):
            return call(board, path, headers={'Cookie': 'lll_board=' + tok})

        def post(tok, body):
            return call(board, '/bot', body, headers={'Cookie': 'lll_board=' + tok, 'Origin': board}, form=True)

        # --- only a read-write member viewer is offered the button ---
        assert 'Add a bot' in page('/t/ALPHA/', rw_tok)[1], 'rw member viewer has no Add a bot'
        for tok in [ro_tok, full]:
            assert 'Add a bot' not in page('/t/ALPHA/', tok)[1], 'button offered to a viewer that cannot mint'

        # Live streams open before the mint, to prove it never reaches them.
        def stream(path, tok, name):
            out = root / f'{name}.log'
            proc = subprocess.Popen(['curl', '-sN', '-H', f'Cookie: lll_board={tok}', board + path],
                                    stdout=out.open('w'), stderr=subprocess.DEVNULL, start_new_session=True)
            streams.append(proc)
            return out

        def wait_for(out, needle):
            deadline = time.monotonic() + 15
            while needle not in out.read_text() and time.monotonic() < deadline:
                time.sleep(.1)
            assert needle in out.read_text(), f'{out.name}: never saw {needle!r}'

        live = [stream('/events?team=ALPHA', rw_tok, 'writer-board'), stream('/events?team=ALPHA', full, 'full-board'),
                stream('/events?page=issue&key=ALPHA-1', rw_tok, 'writer-issue')]
        for out in live:
            wait_for(out, 'alpha work')

        # --- the mint: owned by the viewer, scoped like it, shown once ---
        code, body = post(rw_tok, {'name': 'agent1', 'team': 'ALPHA'})
        assert code == 200, (code, body)
        # The SSE body as the browser assembles it: one element line per data line.
        text = '\n'.join(l.removeprefix('data: elements ') for l in html.unescape(body).splitlines())
        found = TOKEN.search(text)
        assert found, text
        bot_tok = found.group(1)
        assert text.count(bot_tok) == 1, 'the response printed the token more than once'
        assert f'export LLL_URL={board}\n' in text and '\nlll attach --key ALPHA\n' in text, text
        assert "true 'You are joining lll team ALPHA at " + board + ".'" in text, text
        assert '#' not in text[text.index("<pre"):text.index('</pre>')], 'the prompt relies on #'
        bot = members()['bot-agent1']
        assert (bot['kind'], bot['owner'], bot['scope'], bot['teams'], bot['mode']) == \
            ('bot', writer['id'], 'teams', [alpha['id']], 'rw'), bot

        # Pasted into a fresh shell with an empty HOME: the owner's team only.
        agent = root / 'agent'
        (agent / 'work').mkdir(parents=True)
        (agent / 'exports.sh').write_text(''.join(l + '\n' for l in text.splitlines() if l.startswith('export ')))
        ran = subprocess.run(['/bin/sh', '-c', '. ../exports.sh && "$0" issue list && "$0" issue list --team BETA', binary],
                             cwd=agent / 'work', env={'HOME': str(agent), 'PATH': os.environ['PATH']},
                             text=True, capture_output=True, timeout=30)
        assert 'alpha work' in ran.stdout and 'beta secret' not in ran.stdout, ran.stdout + ran.stderr
        assert "no team 'BETA'" in ran.stderr, ran.stderr

        # Never re-rendered: reloads, the live streams (after a later change
        # has flushed through), and the server log.
        for path in ['/t/ALPHA/', '/t/ALPHA/issues', '/t/ALPHA/issue/ALPHA-1', '/t/ALPHA/search?q=agent1']:
            for tok in [rw_tok, full]:
                assert bot_tok not in str(page(path, tok)[1]), f'{path} re-rendered the bot token'
        alpha1 = next(i for i in call(api, '/api/collections/issues/records', token=su)[1]['items'] if i['title'] == 'alpha work')
        call(api, f"/api/collections/issues/records/{alpha1['id']}", {'title': 'alpha after mint'}, su, 'PATCH')
        for out in live:
            wait_for(out, 'alpha after mint')
            assert bot_tok not in out.read_text(), f'{out.name} carried the bot token'
        assert bot_tok not in log.read_text(), 'the server log carried the bot token'

        # --- refusals, none of which creates or rotates anything ---
        before = set(members())

        def refused(tok, form, status, words):
            code, body = post(tok, form)
            assert code == status and words in html.unescape(str(body)), (form, code, body)
            assert not TOKEN.search(html.unescape(str(body))), 'a refusal printed a token'

        refused(ro_tok, {'name': 'ro1', 'team': 'ALPHA'}, 403, 'read-only board login')
        refused(full, {'name': 'full1', 'team': 'ALPHA'}, 200, 'needs a member board login')
        refused(rw_tok, {'name': 'beta1', 'team': 'BETA'}, 200, "no team with key 'BETA'")
        refused(rw_tok, {'name': 'agent1', 'team': 'ALPHA'}, 200, "a member named 'bot-agent1' already exists")
        for name in ['', '../x', 'Agent', 'a b', "x'y", 'a' * 41]:
            refused(rw_tok, {'name': name, 'team': 'ALPHA'}, 200, 'lowercase letters, digits and dashes')
        # A Host the prompt refuses to echo is refused before anything is
        # created: no orphan bot without a prompt.
        code, body = call(board, '/bot', {'name': 'orphan1', 'team': 'ALPHA'}, form=True,
                          headers={'Cookie': 'lll_board=' + rw_tok, 'Host': 'a_b.example:1',
                                   'Origin': 'http://a_b.example:1'})
        assert code == 200 and "cannot tell this board's address" in html.unescape(str(body)), (code, body)
        # The minted bot cannot mint bots from its own cookie.
        assert 'Add a bot' not in page('/t/ALPHA/', bot_tok)[1]
        code, body = post(bot_tok, {'name': 'grandchild', 'team': 'ALPHA'})
        assert code == 200 and not TOKEN.search(html.unescape(str(body))), body
        assert set(members()) == before, set(members()) ^ before
        assert call(api, '/api/collections/issues/records?perPage=1', token=bot_tok)[0] == 200, \
            'a refused re-mint rotated the existing bot token'

        # A team key or url outside the prompt allowlist is refused on both
        # paths before any bot exists (LLL-546 review; the server does not
        # validate keys yet, LLL-628).
        evil_keys = ["Q\r\x1b[KTOUCH PWNCR;: '", "Q\\';TOUCH PWNE2E;ECHO '"]
        evil_ids = []
        for key in evil_keys:
            code, team = call(api, '/api/collections/teams/records', {'key': key, 'name': 'evil'}, su)
            assert code == 200, team
            evil_ids.append(team['id'])
        call(api, f"/api/collections/members/records/{writer['id']}", {'teams': [alpha['id']] + evil_ids}, su, 'PATCH')
        cli_env = {k: v for k, v in env.items() if not k.startswith('LLL_')}
        cli_env.update(HOME=str(root / 'home'), LLL_URL=api, LLL_TOKEN=rw_tok)
        for i, key in enumerate(evil_keys):
            stored = call(api, f"/api/collections/teams/records/{evil_ids[i]}", token=su)[1]['key']
            code, body = post(rw_tok, {'name': f'evil{i}', 'team': stored})
            text = html.unescape(str(body))
            assert code == 200 and 'team key' in text and 'rename the team' in text, (key, text)
            assert not TOKEN.search(text)
            out = subprocess.run([binary, 'bot', f'bot-evilcli{i}', '--team', stored], cwd=root, env=cli_env,
                                 text=True, capture_output=True, timeout=30)
            assert out.returncode != 0 and 'team key' in out.stderr and 'LLL_TOKEN' not in out.stdout, \
                out.stdout + out.stderr
        url_env = dict(cli_env, LLL_URL=api.replace('http://', 'http://u@'))
        out = subprocess.run([binary, 'bot', 'bot-evilurl', '--team', 'ALPHA', '--env'], cwd=root, env=url_env,
                             text=True, capture_output=True, timeout=30)
        assert out.returncode != 0 and 'server url' in out.stderr and out.stdout == '', out.stdout + out.stderr
        assert set(members()) == before, set(members()) ^ before
        # 'bot-' typed into the name is accepted, not doubled.
        code, body = post(rw_tok, {'name': 'bot-agent2', 'team': 'ALPHA'})
        assert code == 200 and TOKEN.search(html.unescape(body)), body
        # The response carries a token: no cache may keep it.
        assert LAST_HEADERS[0]['Cache-Control'] == 'no-store', dict(LAST_HEADERS[0])
        assert 'bot-agent2' in members()
    finally:
        for proc in streams:
            proc.terminate()
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
print('board add a bot: ok')
