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
        # Status on stderr, the handoff alone on stdout (fleet case 11), so
        # '> handoff.txt' captures exactly what to send.
        assert ': read-write, team ALPHA' in out.stderr, out.stderr
        assert 'invited' not in out.stdout and 'temporary password' in out.stdout, out.stdout
        password = re.search(r'temporary password: (\S+)', out.stdout).group(1)
        link = re.search(r'view-only web board for ALPHA \(.*?\): (\S+)', out.stdout).group(1)
        assert link.startswith(board + '/t/ALPHA/?board_token=ALPHA.'), link
        assert env['LLL_BOARD_TOKEN'] not in link, 'scoped link leaked the full board token'

        _, auth, _ = call(api, '/api/collections/members/auth-with-password',
                          {'identity': 'guest@example.test', 'password': password})
        tok, me = auth['token'], auth['record']['id']
        assert auth['record']['teams'] == [alpha['id']], auth['record']
        assert (auth['record']['scope'], auth['record']['mode']) == ('teams', 'rw'), auth['record']

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
        assert status(f'/api/collections/members/records/{me}', {'scope': 'all'}, 'PATCH') == 404
        assert status(f'/api/collections/members/records/{me}', {'mode': 'rw'}, 'PATCH') == 404
        assert status(f'/api/collections/members/records/{me}', {'name': 'guest2'}, 'PATCH') == 200
        assert status('/api/collections/members/records', {'name': 'evil', 'email': 'e@example.test', 'password': 'pw12345678',
                                                           'passwordConfirm': 'pw12345678', 'kind': 'person'}) == 400
        assert status('/api/collections/teams/records', {'key': 'ZETA', 'name': 'z'}) == 400
        # The custom routes read through the app, past the rules; they check too.
        assert status(f"/api/lll/issues/{ib['id']}/claim", {}) == 404
        assert status(f"/api/lll/issues/{ib['id']}/refs", {'ref': 'https://example.test/pr/1'}) == 404
        assert status(f"/api/lll/issues/{ia['id']}/claim", {}) == 200
        assert status(f"/api/lll/issues/{ib['id']}/renew", {'claim_id': 'x'}) == 404, 'renew skips the scope check'
        # Claims leave only through /release (LLL-512): this migration runs
        # after claim_delete_admin and must not reopen direct DELETE.
        _, held, _ = call(api, '/api/collections/claims/records', token=tok)
        assert held['items'], held
        claim_path = f"/api/collections/claims/records/{held['items'][0]['id']}"
        assert status(claim_path, method='DELETE') == 403
        assert status(claim_path) == 200, 'the refused DELETE removed the claim'

        def member_login(name):
            _, a, _ = call(api, '/api/collections/members/auth-with-password',
                           {'identity': f'{name}@example.test', 'password': 'pw12345678'})
            return a['record'], a['token']

        def member(name, **access):
            body = {'name': name, 'email': f'{name}@example.test', 'password': 'pw12345678',
                    'passwordConfirm': 'pw12345678', 'kind': 'person', **access}
            code, rec, _ = call(api, '/api/collections/members/records', body, su)
            assert code == 200, rec
            _, a, _ = call(api, '/api/collections/members/auth-with-password',
                           {'identity': body['email'], 'password': body['password']})
            return rec, a['token']

        # Created with no scope or mode: the creator's, never blank.
        plain, _ = member('plain')
        assert (plain['scope'], plain['mode']) == ('all', 'rw'), plain
        # Read-only: sees ALPHA, writes nothing, custom routes included.
        ro_rec, ro = member('reader', scope='teams', teams=[alpha['id']], mode='ro')
        assert {i['title'] for i in call(api, '/api/collections/issues/records', token=ro)[1]['items']} == \
            {'alpha edited', 'ok'}, 'ro member cannot read its team'
        # Refusals name the reason (fleet case 02). The answer is the same for
        # a BETA row and for an id that does not exist, so it reveals nothing.
        for code_body in [call(api, '/api/collections/issues/records', {'team': alpha['id'], 'title': 'n', 'state': 'todo'}, ro),
                          call(api, f"/api/collections/issues/records/{ia['id']}", {'title': 'n'}, ro, 'PATCH'),
                          call(api, f"/api/collections/issues/records/{ia['id']}", token=ro, method='DELETE'),
                          call(api, '/api/collections/comments/records', {'issue': ia['id'], 'body': 'n'}, ro)]:
            assert code_body[0] == 403 and 'read-only access: reader' in code_body[1]['message'].lower(), code_body[:2]
        for target in [ib['id'], 'nosuchrecord123']:
            assert call(api, f"/api/collections/issues/records/{target}", {'title': 'n'}, ro, 'PATCH')[0] == 403
            assert call(api, f"/api/collections/issues/records/{target}", token=ro, method='DELETE')[0] == 403
        assert call(api, f"/api/collections/members/records/{ro_rec['id']}", {'name': 'reader2'}, ro, 'PATCH')[0] == 200, \
            'ro may still edit its own profile'
        cli_ro = {k: v for k, v in cli.items() if not k.startswith('LLL_ADMIN_')}
        cli_ro.update(LLL_URL=api, LLL_TOKEN=ro, LLL_TEAM='ALPHA')
        who = subprocess.run([binary, 'whoami'], cwd=root, env=cli_ro, text=True, capture_output=True, timeout=30)
        assert 'access  read-only, team ALPHA' in who.stdout, who.stdout + who.stderr
        who = subprocess.run([binary, 'whoami'], cwd=root, env=dict(cli_ro, LLL_TOKEN=tok), text=True, capture_output=True, timeout=30)
        assert 'access  read-write, team ALPHA' in who.stdout, who.stdout + who.stderr
        # Fleet case 03: member list shows access by team key; a scoped
        # caller asking for another team is told it is not one of its own.
        guest_env = dict(cli_ro, LLL_TOKEN=tok)
        listed = subprocess.run([binary, 'member', 'list'], cwd=root, env=guest_env, text=True, capture_output=True, timeout=30)
        assert 'guest2\tguest@example.test\trw ALPHA' in listed.stdout, listed.stdout + listed.stderr
        assert 'ro ALPHA' in listed.stdout and 'rw every team (server-wide)' in listed.stdout, listed.stdout
        assert 'BETA' not in listed.stdout, 'member list named a team the caller cannot see'
        js = json.loads(subprocess.run([binary, 'member', 'list', '--json'], cwd=root, env=guest_env, text=True,
                                       capture_output=True, timeout=30).stdout)
        g = next(m for m in js['items'] if m['name'] == 'guest2')
        assert g['team_keys'] == ['ALPHA'], g
        (root / 'attach-dir').mkdir(exist_ok=True)
        att = subprocess.run([binary, 'attach'], cwd=root / 'attach-dir', env=guest_env, text=True,
                             capture_output=True, timeout=30)
        assert 'you can see one team, ALPHA' in att.stdout + att.stderr, att.stdout + att.stderr
        added = subprocess.run([binary, 'member', 'add', 'sneaky'], cwd=root, env=guest_env, text=True, capture_output=True, timeout=30)
        assert added.returncode != 0 and 'your token cannot add members' in added.stderr, added.stderr
        team_help = subprocess.run([binary, 'team', '--help'], cwd=root, env=guest_env, text=True, capture_output=True, timeout=30)
        assert 'answers\nexactly like a team that does not exist' in team_help.stdout, team_help.stdout
        other = subprocess.run([binary, 'issue', 'list', '--team', 'BETA'], cwd=root, env=guest_env, text=True,
                               capture_output=True, timeout=30)
        assert other.returncode != 0 and "no team 'BETA' among the teams you can see (ALPHA)" in other.stderr, other.stderr
        assert 'team create' not in other.stderr, other.stderr

        # Fleet cases 04, 06-08: invite read-only, then narrow, widen, revoke
        # with 'lll member access', as a full member (not the superuser).
        plain_rec, plain_tok = member_login('plain')
        full_env = dict(cli_ro, LLL_TOKEN=plain_tok)
        admin_env = dict(full_env, LLL_ADMIN_EMAIL=env['LLL_ADMIN_EMAIL'], LLL_ADMIN_PASSWORD=env['LLL_ADMIN_PASSWORD'])

        def lll(*argv, env=full_env):
            return subprocess.run([binary, *argv], cwd=root, env=env, text=True, capture_output=True, timeout=30)

        out = lll('member', 'invite', 'viewer', '--email', 'viewer@example.test', '--team', 'ALPHA', '--read-only',
                  env=cli)
        assert out.returncode == 0 and 'invited viewer <viewer@example.test>: read-only, team ALPHA' in out.stderr, \
            out.stdout + out.stderr
        assert 'view-only web board for ALPHA (separate from their CLI access' in out.stdout, out.stdout
        out = lll('invite')
        assert "it is a member verb: 'lll member invite ...'" in out.stderr, out.stderr
        out = lll('member', 'invite', 'nope', '--email', 'nope@example.test', '--team', 'NOPE', env=cli)
        assert out.returncode != 0 and "no team with key 'NOPE' on this server; teams: ALPHA, BETA" in out.stderr, out.stderr
        steps = [
            ([], 'viewer: read-only, team ALPHA'),
            (['--add-team', 'BETA'], 'viewer: read-only, teams ALPHA, BETA (was read-only, team ALPHA)'),
            (['--remove-team', 'beta', '--read-write'], 'viewer: read-write, team ALPHA (was read-only, teams ALPHA, BETA)'),
            (['--no-teams'], 'viewer: read-write, no teams (was read-write, team ALPHA)'),
            (['--team', 'ALPHA', '--team', 'BETA'], 'viewer: read-write, teams ALPHA, BETA (was read-write, no teams)'),
            (['--all-teams', '--read-only'], 'viewer: read-only, every team (server-wide) (was read-write, teams ALPHA, BETA)'),
            (['--read-only'], 'viewer: read-only, every team (server-wide) (unchanged)'),
        ]
        for flags_, want in steps:
            out = lll('member', 'access', 'viewer', *flags_, env=admin_env)
            assert out.returncode == 0 and want in out.stdout, (flags_, out.stdout, out.stderr)
        for bad in [['--team', 'ALPHA', '--all-teams'], ['--read-only', '--read-write'], ['--add-team', 'ALPHA']]:
            out = lll('member', 'access', 'viewer', *bad, env=admin_env)
            assert out.returncode != 0, (bad, out.stdout)
        out = lll('member', 'access', 'viewer', '--read-write', env=guest_env)
        assert out.returncode != 0, 'a scoped member changed someone else\'s access'
        out = lll('member', 'access', 'guest2', '--all-teams', env=guest_env)
        assert out.returncode != 0, 'a scoped member widened itself'
        # Only administrator credentials change access: a full member's (or
        # bot's) token alone cannot, through the CLI or the API.
        out = lll('member', 'access', 'viewer', '--team', 'ALPHA')
        assert out.returncode != 0 and 'admin' in (out.stdout + out.stderr).lower(), out.stdout + out.stderr
        viewer_id = next(m for m in call(api, '/api/collections/members/records?perPage=200', token=su)[1]['items']
                         if m['name'] == 'viewer')['id']
        for body in [{'mode': 'rw'}, {'scope': 'teams', 'teams': [alpha['id']]}, {'teams+': [beta['id']]}]:
            assert call(api, f'/api/collections/members/records/{viewer_id}', body, plain_tok, 'PATCH')[0] == 404, body
            assert call(api, f"/api/collections/members/records/{plain_rec['id']}", body, plain_tok, 'PATCH')[0] == 404, body
        assert call(api, f'/api/collections/members/records/{viewer_id}', {'name': 'viewer'}, plain_tok, 'PATCH')[0] == 200, \
            'control: a full member still edits other fields'
        assert call(api, f"/api/lll/issues/{ia['id']}/refs", {'ref': 'https://example.test/pr/2'}, ro)[0] == 403
        assert call(api, '/api/collections/favorites/records', {'issue': ia['id'], 'member': ro_rec['id']}, ro)[0] == 200, \
            'ro keeps favorites'
        # A bot minted while its owner was "all" stays "all"; narrowing the
        # owner must stop the owner minting fresh tokens for it.
        owner, owner_tok = member('owner')
        code, rot, _ = call(api, '/api/collections/members/records',
                            {'name': 'bot-owned', 'email': 'bot-owned@example.test', 'password': 'pw12345678',
                             'passwordConfirm': 'pw12345678', 'kind': 'bot', 'owner': owner['id']}, su)
        assert code == 200, rot
        assert call(api, '/api/lll/bots/rotate', {'name': 'bot-owned'}, owner_tok)[0] == 200
        call(api, f"/api/collections/members/records/{owner['id']}", {'scope': 'teams', 'teams': [alpha['id']]}, su, 'PATCH')
        _, owner_tok = member_login('owner')
        assert call(api, '/api/lll/bots/rotate', {'name': 'bot-owned'}, owner_tok)[0] == 403
        assert call(api, '/api/lll/bots/rotate', {'name': 'bot-owned'}, su)[0] == 200
        # Saved views and favorites are a narrower member's own (review of #172).
        _, other_view, _ = call(api, '/api/collections/views/records',
                                {'name': 'secret', 'query': 'team=BETA&q=beta+secret', 'member': plain['id']}, su)
        _, mine, _ = call(api, '/api/collections/views/records', {'name': 'mine', 'query': 'team=ALPHA', 'member': me}, tok)
        assert mine.get('id'), mine
        assert [v['name'] for v in items('/api/collections/views/records')] == ['mine']
        assert call(api, f"/api/collections/views/records/{other_view['id']}", {'query': 'x'}, ro, 'PATCH')[0] == 404
        assert call(api, f"/api/collections/views/records/{other_view['id']}", token=ro, method='DELETE')[0] == 404
        assert status('/api/collections/views/records', {'name': 'n', 'query': 'q', 'member': plain['id']}) == 400
        assert status(f"/api/collections/views/records/{mine['id']}", {'member': plain['id']}, 'PATCH') == 404
        _, their_fav, _ = call(api, '/api/collections/favorites/records', {'issue': ia['id'], 'member': plain['id']}, su)
        assert status(f"/api/collections/favorites/records/{their_fav['id']}", method='DELETE') == 404
        assert status('/api/collections/favorites/records', {'issue': ia['id'], 'member': plain['id']}) == 400
        assert their_fav['id'] not in [f['id'] for f in items('/api/collections/favorites/records')]
        assert len(call(api, '/api/collections/views/records', token=su)[1]['items']) == 2, 'control: both views exist'

        # No pointing an ALPHA row at BETA's project, labels or issues, even
        # with the ids in hand: the board would render BETA's names.
        _, bproj, _ = call(api, '/api/collections/projects/records', {'team': beta['id'], 'name': 'beta-proj', 'status': 'planned'}, su)
        _, blabel, _ = call(api, '/api/collections/labels/records', {'team': beta['id'], 'name': 'beta-label'}, su)
        _, aproj, _ = call(api, '/api/collections/projects/records', {'team': alpha['id'], 'name': 'alpha-proj', 'status': 'planned'}, su)
        assert status('/api/collections/issues/records',
                      {'team': alpha['id'], 'title': 'x', 'state': 'todo', 'project': bproj['id']}) == 400
        assert status(f"/api/collections/issues/records/{ia['id']}", {'labels+': [blabel['id']]}, 'PATCH') == 400
        assert status(f"/api/collections/issues/records/{ia['id']}", {'blocked_by+': [ib['id']]}, 'PATCH') == 400
        assert status('/api/collections/docs/records', {'team': alpha['id'], 'slug': 's1', 'title': 't',
                                                        'kind': 'note', 'body': 'b', 'issues': [ib['id']]}) == 400
        assert status('/api/collections/webhooks/records', {'team': alpha['id'], 'project': bproj['id'],
                                                            'url': 'https://example.test/h'}) == 400
        assert status(f"/api/lll/issues/{ia['id']}/assignment",
                      {'claim_id': '', 'fields': {'assignee': '', 'labels': [blabel['id']]}}) == 400
        assert status(f"/api/collections/issues/records/{ia['id']}", {'project': aproj['id']}, 'PATCH') == 200, \
            'control: same-team project accepted'
        # A link an all-scope member made does not block the scoped member's edit.
        call(api, f"/api/collections/issues/records/{ia['id']}", {'blocked_by+': [ib['id']]}, su, 'PATCH')
        assert status(f"/api/collections/issues/records/{ia['id']}", {'title': 'alpha edited'}, 'PATCH') == 200

        # Scope "teams" with no teams sees nothing: empty never means every team.
        _, none = member('nobody', scope='teams', teams=[])
        assert call(api, '/api/collections/issues/records', token=none)[1]['items'] == []
        assert call(api, '/api/collections/teams/records', token=none)[1]['items'] == []

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
        # Fleet case 05: 'lll board --team KEY' gives the same view-only link
        # without creating a member.
        out = subprocess.run([binary, 'board', '--team', 'alpha'], cwd=root, env=dict(cli, LLL_TOKEN=su), text=True, capture_output=True, timeout=30)
        assert out.returncode == 0 and out.stdout.strip() == link, (out.stdout, out.stderr, link)
        out = subprocess.run([binary, 'board', '--team', 'NOPE'], cwd=root, env=dict(cli, LLL_TOKEN=su), text=True, capture_output=True, timeout=30)
        assert out.returncode != 0 and 'NOPE' in out.stderr, out.stderr
        no_tok = {k: v for k, v in cli.items() if k != 'LLL_BOARD_TOKEN'}
        no_tok['LLL_TOKEN'] = su
        no_tok['LLL_CONFIG_HOME'] = str(root / 'empty-config')
        no_tok['HOME'] = str(root / 'empty-home')
        out = subprocess.run([binary, 'board', '--team', 'ALPHA'], cwd=root, env=no_tok, text=True, capture_output=True, timeout=30)
        assert out.returncode != 0 and 'board token' in out.stderr, out.stdout + out.stderr

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
        # Deleting a scoped member's only team leaves it seeing nothing, not
        # everything: scope is explicit, so no delete guard is needed.
        _, gamma, _ = call(api, '/api/collections/teams/records', {'key': 'GAMMA', 'name': 'g'}, su)
        _, solo = member('solo', scope='teams', teams=[gamma['id']])
        assert [t['key'] for t in call(api, '/api/collections/teams/records', token=solo)[1]['items']] == ['GAMMA']
        assert call(api, f"/api/collections/teams/records/{gamma['id']}", token=su, method='DELETE')[0] == 204
        assert call(api, '/api/collections/teams/records', token=solo)[1]['items'] == []
        assert call(api, '/api/collections/issues/records', token=solo)[1]['items'] == []
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
