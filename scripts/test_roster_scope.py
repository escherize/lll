#!/usr/bin/env python3
"""LLL-551: the members roster a team-scoped member sees.

A member limited to some teams sees itself, members that share one of its
teams and people (not bots) with access to every team, and no email but its
own. Checked over the raw API (list, view, expand, filter, sort, realtime),
the CLI and the board's member cookie (pages, raw, search, live stream). A
full-access member keeps the whole roster and every email."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
# What an ALPHA-only guest must never read: other members' names and emails
# and the hidden team.
HIDDEN = ['bot-garden', 'beta-only', 'bot-beta', '@example.test', 'BETA', 'Bravo Hidden Team']
GUEST_EMAIL = 'alpha-guest@example.test'


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
    return resp.status, text


def clean(text, where, allow_own_email=True):
    text = str(text)
    if allow_own_email:
        text = text.replace(GUEST_EMAIL, '')
    for marker in HIDDEN:
        assert marker not in text, f'{where} leaked {marker!r}'


with tempfile.TemporaryDirectory(prefix='lll-551-') as directory:
    root = Path(directory)
    (root / 'home').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root / 'home'), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='board-owner', LLL_ADMIN_EMAIL='roster@example.invalid',
               LLL_ADMIN_PASSWORD='local-roster-scope-password', LLL_BOARD_TOKEN='local-roster-scope-board')
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
        gamma = call(api, '/api/collections/teams/records', {'key': 'GAMMA', 'name': 'Gamma'}, su)[1]

        ids, toks = {}, {}

        def member(name, kind='person', owner='', **access):
            body = {'name': name, 'email': f'{name}@example.test', 'password': 'pw12345678',
                    'passwordConfirm': 'pw12345678', 'kind': kind, 'emailVisibility': True, **access}
            if owner:
                body['owner'] = owner
            code, rec = call(api, '/api/collections/members/records', body, su)
            assert code == 200, rec
            code, tok = call(api, f"/api/collections/members/impersonate/{rec['id']}", {'duration': 3600}, su)
            assert code == 200, tok
            ids[name], toks[name] = rec['id'], tok['token']

        member('alpha-guest', scope='teams', teams=[alpha['id']], mode='rw')
        member('beta-only', scope='teams', teams=[beta['id']], mode='rw')
        member('bot-beta', kind='bot', scope='teams', teams=[beta['id']], mode='rw')
        member('full-person', scope='all', mode='rw')
        member('bot-garden', kind='bot', scope='all', mode='rw')
        member('both', scope='teams', teams=[alpha['id'], beta['id']], mode='rw')
        # An owned bot narrowed to no team: its own teams say ALPHA, its
        # owner's say GAMMA. 'split' shares ALPHA with the bot and GAMMA with
        # the owner, but no team with both, so the bot must not see it.
        member('owner', scope='teams', teams=[alpha['id'], gamma['id']], mode='rw')
        member('bot-owned', kind='bot', owner=ids['owner'], scope='teams', teams=[alpha['id']], mode='rw')
        assert call(api, f"/api/collections/members/records/{ids['owner']}", {'teams': [gamma['id']]}, su, 'PATCH')[0] == 200
        member('split', scope='teams', teams=[alpha['id'], gamma['id']], mode='rw')

        code, issue = call(api, '/api/collections/issues/records', {'team': alpha['id'], 'title': 'alpha work', 'state': 'todo',
                                                                    'assignee': ids['bot-garden'], 'creator': ids['bot-garden']}, su)
        assert code == 200, issue
        assert call(api, '/api/collections/claims/records', {'issue': issue['id'], 'member': ids['bot-garden']}, su)[0] == 200
        for author, body in [('bot-garden', 'garden note'), ('full-person', 'full note'), ('alpha-guest', 'guest note')]:
            assert call(api, '/api/collections/comments/records', {'issue': issue['id'], 'author': ids[author], 'body': body}, su)[0] == 200
        assert call(api, '/api/collections/issues/records', {'team': beta['id'], 'title': 'zebra', 'state': 'todo',
                                                             'assignee': ids['bot-beta']}, su)[0] == 200

        # --- the rule: who lists whom ---
        def names(who):
            code, body = call(api, '/api/collections/members/records?perPage=200', token=toks[who])
            assert code == 200, body
            return sorted(m['name'] for m in body['items'])

        everyone = sorted(['board-owner', *ids])
        assert names('full-person') == everyone and names('bot-garden') == everyone
        assert names('alpha-guest') == sorted(['alpha-guest', 'board-owner', 'both', 'bot-owned', 'full-person', 'split']), names('alpha-guest')
        assert names('bot-beta') == sorted(['beta-only', 'board-owner', 'bot-beta', 'both', 'full-person']), names('bot-beta')
        assert names('bot-owned') == sorted(['board-owner', 'bot-owned', 'full-person']), names('bot-owned')

        # Emails: only its own for a scoped member, every one for full access.
        code, body = call(api, '/api/collections/members/records?perPage=200', token=toks['alpha-guest'])
        emails = {m['name']: m.get('email', '') for m in body['items']}
        assert emails['alpha-guest'] == GUEST_EMAIL and all(v == '' for k, v in emails.items() if k != 'alpha-guest'), emails
        # A visible member's teams carry no hidden team id.
        both = next(m for m in body['items'] if m['name'] == 'both')
        assert both['teams'] == [alpha['id']], both
        clean(body, 'guest member list')
        code, body = call(api, '/api/collections/members/records?perPage=200', token=toks['full-person'])
        assert all(m.get('email') for m in body['items']), 'full access lost an email'
        assert call(api, f"/api/collections/members/records/{ids['bot-garden']}", token=toks['alpha-guest'])[0] == 404
        assert call(api, f"/api/collections/members/records/{ids['full-person']}", token=toks['alpha-guest'])[0] == 200

        # Expansion through visible records stops at the hidden member.
        code, body = call(api, '/api/collections/issues/records?expand=assignee,creator', token=toks['alpha-guest'])
        assert code == 200 and body['items'][0]['assignee'] == ids['bot-garden'], body
        clean(body, 'issues expand')
        for path in ['/api/collections/comments/records?expand=author.owner',
                     '/api/collections/claims/records?expand=member']:
            code, body = call(api, path, token=toks['alpha-guest'])
            assert code == 200, (path, body)
            clean(body, path)

        # Filters and sorts that walk into or out of members are refused for
        # a scoped caller; the same filters work at full access.
        probes = ['/api/collections/issues/records?filter=' + urllib.parse.quote('assignee.name ~ "bot-g%"'),
                  '/api/collections/issues/records?sort=assignee.name',
                  '/api/collections/comments/records?filter=' + urllib.parse.quote('author.kind = "bot"'),
                  '/api/collections/claims/records?filter=' + urllib.parse.quote('member.name ~ "g"'),
                  '/api/collections/members/records?filter=' + urllib.parse.quote('issues_via_assignee.title ~ "zebra"'),
                  '/api/collections/members/records?filter=' + urllib.parse.quote('teams.key = "BETA"'),
                  '/api/collections/teams/records?filter=' + urllib.parse.quote('members_via_teams.name ~ "bot"'),
                  # Review F2, F3: an email sort and the stored team ids are oracles.
                  '/api/collections/members/records?sort=email',
                  '/api/collections/members/records?filter=' + urllib.parse.quote('teams:length = 2'),
                  '/api/collections/members/records?filter=' + urllib.parse.quote('teams ~ "x"')]
        for path in probes:
            code, body = call(api, path, token=toks['alpha-guest'])
            assert code == 403, (path, code, body)
            assert call(api, path, token=toks['full-person'])[0] == 200, path
        # Email filters are refused for a scoped caller.
        code, body = call(api, '/api/collections/members/records?filter=' + urllib.parse.quote('email ~ "full"'), token=toks['alpha-guest'])
        assert code == 403, body
        code, body = call(api, '/api/collections/issues/records?filter=' + urllib.parse.quote(f'assignee = "{ids["bot-garden"]}"'), token=toks['alpha-guest'])
        assert code == 200 and body['totalItems'] == 1, 'control: filtering on a relation id still works'

        # Realtime: a subscription that filters through members is refused.
        def realtime_subscribe(token, topic):
            req = urllib.request.Request(api + '/api/realtime')
            resp = urllib.request.urlopen(req, timeout=10)
            client = None
            while client is None:
                line = resp.readline().decode()
                if line.startswith('data:'):
                    client = json.loads(line[5:])['clientId']
            code, body = call(api, '/api/realtime', {'clientId': client, 'subscriptions': [topic]}, token)
            resp.close()
            return code, body

        probe = 'issues/*?options=' + urllib.parse.quote(json.dumps({'query': {'filter': 'assignee.name ~ "bot-g%"'}}))
        assert realtime_subscribe(toks['alpha-guest'], probe)[0] == 403
        # PocketBase reads "options" from anywhere in the topic's query, so
        # the guard must too (review F1).
        options = urllib.parse.quote(json.dumps({'query': {'filter': "teams.key !~ 'B%'"}}))
        for topic in [f'members/*?x=1&options={options}', f'members/*?opt%69ons={options}']:
            assert realtime_subscribe(toks['alpha-guest'], topic)[0] == 403, topic
        assert realtime_subscribe(toks['full-person'], probe)[0] == 204
        assert realtime_subscribe(toks['alpha-guest'], 'issues/*')[0] == 204

        # A member cannot make its own email public again.
        assert call(api, f"/api/collections/members/records/{ids['full-person']}", {'emailVisibility': True},
                    toks['full-person'], 'PATCH')[0] == 200
        code, body = call(api, f"/api/collections/members/records/{ids['full-person']}", token=toks['alpha-guest'])
        assert code == 200 and body.get('email', '') == '', body

        # A custom route names a hidden claim holder as hidden.
        code, body = call(api, f"/api/lll/issues/{issue['id']}/claim", {}, toks['alpha-guest'], 'POST')
        assert code == 400 and 'a hidden member' in body['message'] and 'garden' not in str(body), body

        # --- the CLI ---
        def lll(who, *args):
            cli_env = {**env, 'LLL_URL': api, 'LLL_TOKEN': toks[who]}
            done = subprocess.run([binary, *args], cwd=root, env=cli_env, capture_output=True, text=True, timeout=60)
            return done.returncode, done.stdout + done.stderr

        code, out = lll('alpha-guest', 'member', 'list')
        assert code == 0 and 'full-person\t(hidden)' in out, out
        clean(out, 'cli member list')
        code, out = lll('alpha-guest', 'issue', 'view', 'ALPHA-1')
        assert code == 0 and 'Assignee:  hidden member' in out and 'Claimed:   hidden member' in out, out
        assert 'full note' in out and 'full-person' in out, out
        clean(out, 'cli issue view')
        for args in [('issue', 'view', 'ALPHA-1', '--raw'), ('issue', 'view', 'ALPHA-1', '--json'), ('issue', 'list'),
                     ('issue', 'comment', 'ALPHA-1'), ('search', 'garden')]:
            code, out = lll('alpha-guest', *args)
            assert code == 0, (args, out)
            clean(out, f'cli {args}')
        code, out = lll('alpha-guest', 'member', 'access', 'bot-garden')
        assert code != 0 and "no member named 'bot-garden'" in out, out
        code, out = lll('full-person', 'issue', 'view', 'ALPHA-1')
        assert 'Assignee:  bot-garden' in out, 'control: full access names the assignee'
        code, member_help = lll('alpha-guest', 'member', '--help')
        code, team_help = lll('alpha-guest', 'team', '--help')
        assert 'Who sees whom' in member_help and 'hidden member' in member_help, member_help
        assert "'lll member --help'" in team_help and "'lll team --help'" in member_help

        # --- the board, as the guest's member cookie ---
        def page(path, who):
            return call(board, path, headers={'Cookie': 'lll_board=' + toks[who]})

        # LLL-643: the docs index names a hidden author as "hidden member".
        assert call(api, '/api/collections/docs/records', {'team': alpha['id'], 'slug': 'garden-doc', 'title': 'garden doc',
                                                           'kind': 'wiki', 'body': 'b', 'author': ids['bot-garden']}, su)[0] == 200
        assert '| hidden member |' in page('/t/ALPHA/docs?raw', 'alpha-guest')[1]
        assert '| bot-garden [bot] |' in page('/t/ALPHA/docs?raw', 'full-person')[1], 'control: full access names the author'
        for path in ['/t/ALPHA/', '/t/ALPHA/?raw', '/t/ALPHA/docs', '/t/ALPHA/docs?raw',
                     '/t/ALPHA/issue/ALPHA-1', '/t/ALPHA/issue/ALPHA-1?raw',
                     '/t/ALPHA/issues', '/t/ALPHA/issues?raw', '/t/ALPHA/search?q=garden', '/t/ALPHA/search?q=note&raw',
                     '/t/ALPHA/search?q=note&fragment=1', '/t/ALPHA/search?q=note&palette=1']:
            code, body = page(path, 'alpha-guest')
            assert code == 200, (path, code)
            clean(body, path)
        assert 'hidden member' in page('/t/ALPHA/issue/ALPHA-1?raw', 'alpha-guest')[1]
        # A hidden name in a filter answers exactly like a name nobody has.
        for tmpl in ['/t/ALPHA/?assignee={}', '/t/ALPHA/issues?assignee={}&raw']:
            a = page(tmpl.format('bot-garden'), 'alpha-guest')
            b = page(tmpl.format('nobody-here'), 'alpha-guest')
            assert a[0] == b[0] and a[1].replace('bot-garden', 'N') == b[1].replace('nobody-here', 'N'), tmpl
        full_page = page('/t/ALPHA/issue/ALPHA-1', 'full-person')[1]
        assert 'bot-garden' in full_page and 'beta-only' in full_page, 'control: a full-access cookie sees everyone'

        # --- the live stream: a hidden bot comments and edits; no name arrives ---
        def stream(path, who, name):
            out = root / f'{name}.log'
            handle = out.open('w')
            proc = subprocess.Popen(['curl', '-sN', '-H', f'Cookie: lll_board={toks[who]}', board + path],
                                    stdout=handle, stderr=subprocess.DEVNULL, start_new_session=True)
            streams.append(proc)
            return out

        def wait_for(out, needle):
            deadline = time.monotonic() + 15
            while needle not in out.read_text() and time.monotonic() < deadline:
                time.sleep(.1)
            assert needle in out.read_text(), f'{out.name}: never saw {needle!r}'

        guest_board = stream('/events?team=ALPHA', 'alpha-guest', 'guest-board')
        guest_issue = stream('/events?page=issue&key=ALPHA-1', 'alpha-guest', 'guest-issue')
        full_issue = stream('/events?page=issue&key=ALPHA-1', 'full-person', 'full-issue')
        for out in [guest_board, guest_issue, full_issue]:
            wait_for(out, 'alpha work')
        assert call(api, '/api/collections/comments/records', {'issue': issue['id'], 'author': ids['bot-garden'],
                                                               'body': 'live garden note'}, su)[0] == 200
        assert call(api, f"/api/collections/issues/records/{issue['id']}", {'title': 'alpha renamed'}, su, 'PATCH')[0] == 200
        for out in [guest_board, guest_issue, full_issue]:
            wait_for(out, 'alpha renamed')
        wait_for(guest_issue, 'live garden note')
        wait_for(full_issue, 'live garden note')
        clean(guest_board.read_text(), 'guest board stream')
        clean(guest_issue.read_text(), 'guest issue stream')
        assert 'bot-garden' in full_issue.read_text(), 'control: the full-access stream names the bot'
    finally:
        for proc in streams:
            proc.terminate()
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
print('roster scope: ok')
