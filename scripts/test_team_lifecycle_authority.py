#!/usr/bin/env python3
"""Team lifecycle belongs to people (LLL-799): a workspace Admin or an
independent person holding the legacy all-team read-write grant may create,
rename, archive, unarchive and delete teams. A bot may not, whatever grant it
and its owner hold, and neither may a worker that bot created."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
REFUSAL = 'Team management refused'


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


with tempfile.TemporaryDirectory(prefix='lll-team-lifecycle-') as directory:
    root = Path(directory)
    home = root / 'home'
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(home), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='FLEET', LLL_BIND='127.0.0.1',
               USER='lifecycle-operator', LLL_ADMIN_EMAIL='lifecycle@local.invalid',
               LLL_ADMIN_PASSWORD='isolated-lifecycle-password', LLL_BOARD_TOKEN='isolated-lifecycle-board')
    log = root / 'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        api = wait_for_endpoints(log)['db_url']

        def call(path, body=None, token='', method=None):
            req = urllib.request.Request(api + path, method=method,
                                         data=None if body is None else json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
            try:
                response = urllib.request.urlopen(req, timeout=15)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None

        def expect(code, path, body=None, token='', method=None):
            status, answer = call(path, body, token, method)
            assert status == code, (path, method, status, answer)
            return answer

        su = expect(200, '/api/collections/_superusers/auth-with-password',
                    {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})['token']
        teams_path = '/api/collections/teams/records'
        members = '/api/collections/members/records'
        # The targets a refused identity aims at: an empty team it could
        # rename, archive or delete, and an archived one it could bring back.
        victim = expect(200, teams_path, {'key': 'SECRET', 'name': 'Payroll'}, su)
        parked = expect(200, teams_path, {'key': 'PARKED', 'name': 'Parked', 'archived': True}, su)

        def member(name, kind, **fields):
            return expect(200, members, {'name': name, 'kind': kind, 'email': name + '@local.invalid',
                                         'password': 'isolated-member-password',
                                         'passwordConfirm': 'isolated-member-password', **fields}, su)

        def token(row):
            return expect(200, '/api/collections/members/impersonate/' + row['id'], {'duration': 3600}, su)['token']

        cli_env = {k: v for k, v in env.items() if not k.startswith('LLL_ADMIN') and k != 'LLL_BOARD_TOKEN'}

        def cli(tok, *args):
            return subprocess.run([binary, *args], cwd=root, env=dict(cli_env, LLL_TOKEN=tok),
                                  capture_output=True, text=True, timeout=30)

        def bot_for(owner_token, name):
            made = cli(owner_token, 'bot', 'create', name, '--json')
            assert made.returncode == 0, (name, made.returncode, made.stderr)
            return json.loads(made.stdout)['token']

        def teams_now():
            rows = expect(200, teams_path + '?perPage=200', token=su)['items']
            return {t['key']: (t['name'], bool(t.get('archived'))) for t in rows}

        # The issue's fixture: a person with the legacy all-team read-write
        # grant who is not an Admin, a bot that person created, and a worker
        # that bot created.
        person = member('fleet-worker', 'person', scope='all', mode='rw')
        assert person.get('workspace_role', 'member') != 'admin'
        person_token = token(person)
        bot_token = bot_for(person_token, 'bot-a')
        worker_token = bot_for(bot_token, 'bot-w')
        rows = {m['name']: m for m in expect(200, members + '?perPage=200', token=su)['items']}
        assert rows['bot-a']['owner'] == person['id'] and rows['bot-a']['scope'] == 'all' and rows['bot-a']['mode'] == 'rw'
        assert rows['bot-w']['owner'] == person['id'] and rows['bot-w']['created_by'] == rows['bot-a']['id']
        assert rows['bot-w']['scope'] == 'all' and rows['bot-w']['mode'] == 'rw'
        # An operator-created bot with no owner held the same grant in 1.8.
        unowned_token = token(member('bot-unowned', 'bot', scope='all', mode='rw'))
        # An Admin with no team data access, and people and bots held to named teams.
        admin_token = token(member('admin-only', 'person', scope='teams', mode='ro', workspace_role='admin'))
        scoped = member('scoped-editor', 'person', scope='teams', mode='ro',
                        teams=[victim['id'], parked['id']], editor_teams=[victim['id'], parked['id']])
        scoped_token = token(scoped)
        scoped_bot_token = bot_for(scoped_token, 'bot-scoped')

        allowed = {'legacy all-team person': person_token, 'workspace Admin': admin_token}
        refused = {'bot under a legacy all-team person': bot_token, 'worker created by that bot': worker_token,
                   'unowned all-team bot': unowned_token, 'team-scoped person': scoped_token,
                   'bot under a team-scoped person': scoped_bot_token}

        before = teams_now()
        for who, tok in refused.items():
            for label, args in [
                ('create', ('team', 'create', 'REP', '-n', 'Rep')),
                ('rename', ('team', 'rename', 'SECRET', '-n', 'Hacked')),
                ('archive', ('team', 'archive', 'SECRET')),
                ('unarchive', ('team', 'unarchive', 'PARKED')),
                ('delete', ('team', 'delete', 'SECRET', '--yes')),
            ]:
                got = cli(tok, *args)
                assert got.returncode == 4 and REFUSAL in got.stderr and 'workspace Admin' in got.stderr, \
                    (who, label, got.returncode, got.stderr)
            # The records API answers the same way, so the CLI is not the guard.
            for path, body, method in [
                (teams_path, {'key': 'REP', 'name': 'Rep'}, None),
                (teams_path + '/' + victim['id'], {'name': 'Hacked'}, 'PATCH'),
                (teams_path + '/' + victim['id'], {'archived': True}, 'PATCH'),
                (teams_path + '/' + parked['id'], {'archived': False}, 'PATCH'),
                (teams_path + '/' + victim['id'], None, 'DELETE'),
            ]:
                status, answer = call(path, body, tok, method)
                assert status == 403 and REFUSAL in answer['message'], (who, path, method, status, answer)
            assert teams_now() == before, (who, teams_now())

        for index, (who, tok) in enumerate(allowed.items()):
            key = f'REP{index}'
            for label, args, state in [
                ('create', ('team', 'create', key, '-n', 'Rep'), ('Rep', False)),
                ('rename', ('team', 'rename', key, '-n', 'Renamed'), ('Renamed', False)),
                ('archive', ('team', 'archive', key), ('Renamed', True)),
                ('unarchive', ('team', 'unarchive', key), ('Renamed', False)),
                ('delete', ('team', 'delete', key, '--yes'), None),
            ]:
                got = cli(tok, *args)
                assert got.returncode == 0, (who, label, got.returncode, got.stderr)
                assert teams_now().get(key) == state, (who, label, teams_now())
        assert teams_now() == before

        # The rules carry the bound themselves; the 403 above only names it.
        rules = expect(200, '/api/collections/teams', token=su)
        person_only = '@request.auth.kind != "bot" && @request.auth.owner = ""'
        for rule in ('createRule', 'updateRule', 'deleteRule'):
            assert person_only in rules[rule], (rule, rules[rule])
        print('team lifecycle authority: 5 refused identities x 5 actions (CLI and API), 2 allowed identities x 5 actions')
    finally:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
