#!/usr/bin/env python3
"""Exercise per-team roles against an isolated server with real migrations.

No service URL or data path is accepted. All identities and credentials are
throwaway; the receipt records decisions, never tokens.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from board_startup import wait_for_endpoints


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    binary = str(args.binary.resolve())
    checks = []
    with tempfile.TemporaryDirectory(prefix='lll-team-roles-') as directory:
        root = Path(directory)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
        env.update(HOME=str(root), USER='roles-operator', LLL_TEAM='ENG', LLL_BIND='127.0.0.1',
                   LLL_URL=f'http://127.0.0.1:{port()}', LLL_ADMIN_EMAIL='roles@local.invalid',
                   LLL_ADMIN_PASSWORD='isolated-roles-password', LLL_BOARD_TOKEN='isolated-roles-board')
        log = root / 'server.log'
        with log.open('w') as output:
            child = subprocess.Popen([binary, 'up', '--no-open', '--pb-dir', str(root / 'data'), '--port', str(port())],
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

            admin = expect(200, '/api/collections/_superusers/auth-with-password',
                           {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})['token']
            teams = expect(200, '/api/collections/teams/records', token=admin)['items']
            eng = next(t['id'] for t in teams if t['key'] == 'ENG')
            finance = expect(200, '/api/collections/teams/records', {'key': 'FIN', 'name': 'Finance'}, admin)['id']
            hidden = expect(200, '/api/collections/teams/records', {'key': 'HID', 'name': 'Hidden'}, admin)['id']
            members = '/api/collections/members/records'

            def person(name, **grants):
                return expect(200, members, {'name': name, 'kind': 'person', 'email': name + '@local.invalid',
                    'password': 'isolated-person-password', 'passwordConfirm': 'isolated-person-password', **grants}, admin)

            def token(member):
                return expect(200, '/api/collections/members/impersonate/' + member['id'], {'duration': 3600}, admin)['token']

            alice = person('alice', scope='teams', mode='ro', teams=[eng, finance], editor_teams=[eng])
            alice_token = token(alice)
            access = expect(200, '/api/lll/access', token=alice_token)
            assert access['permissions_version'] == 2 and access['rw'] is False
            assert {t['id']: t['role'] for t in access['teams']} == {eng: 'editor', finance: 'viewer'}
            checks.append('access reply reports mixed roles with a conservative legacy write projection')
            issues = '/api/collections/issues/records'
            ia = expect(200, issues, {'team': eng, 'title': 'Engineering work', 'state': 'todo'}, alice_token)
            ib = expect(200, issues, {'team': finance, 'title': 'Finance work', 'state': 'todo'}, admin)
            expect(200, issues + '/' + ib['id'], token=alice_token)
            for path, body, method in [
                (issues, {'team': finance, 'title': 'denied', 'state': 'todo'}, None),
                (issues + '/' + ib['id'], {'title': 'denied'}, 'PATCH'),
                (issues + '/' + ib['id'], None, 'DELETE'),
                (issues + '/' + ia['id'], {'team': finance}, 'PATCH'),
            ]:
                status, _ = call(path, body, alice_token, method)
                assert status in (400, 403, 404), (path, method, status)
            expect(200, issues + '/' + ia['id'], {'title': 'allowed'}, alice_token, 'PATCH')
            expect(404, '/api/collections/teams/records/' + hidden, token=alice_token)
            checks.append('native issue writes require Editor on source and destination; Viewer reads and hidden isolation hold')
            for team, issue, allowed in [(eng, ia, True), (finance, ib, False)]:
                status, _ = call('/api/collections/comments/records', {'issue': issue['id'], 'body': 'role check'}, alice_token)
                assert (status == 200) == allowed, ('comment', status)
                status, _ = call('/api/lll/issues/' + issue['id'] + '/refs', {'ref': 'gh#793'}, alice_token)
                assert (status == 200) == allowed, ('reference', status)
            checks.append('native comments and typed custom reference operations agree')
            for field in ['scope', 'mode', 'teams']:
                value = {'scope': 'all', 'mode': 'rw', 'teams': [eng]}[field]
                response = expect(400, members + '/' + alice['id'], {field: value}, admin, 'PATCH')
                assert response['data']['code'] == 'team_roles_required'
            expect(200, members + '/' + alice['id'], {}, alice_token, 'PATCH')
            kept = expect(200, members + '/' + alice['id'], token=admin)
            assert kept['editor_teams'] == [eng] and kept['teams'] == [eng, finance]
            for suffix in ['', '?filter=editor_teams:length%3E0', '?sort=editor_teams']:
                status, _ = call(members + suffix, token=alice_token)
                assert status == (200 if not suffix else 403), (suffix, status)
            expect(404, members + '/' + alice['id'], {'editor_teams': [finance]}, alice_token, 'PATCH')
            checks.append('legacy grant changes refuse before writes; profiles retain roles; role-field filter probes and self-escalation refused')
            bot_body = {'name': 'bot-review', 'kind': 'bot', 'owner': alice['id'], 'email': 'bot@local.invalid',
                        'password': 'isolated-bot-password', 'passwordConfirm': 'isolated-bot-password'}
            bot = expect(200, members, bot_body, alice_token)
            assert bot['mode'] == 'ro' and bot['editor_teams'] == [eng]
            bot_token = token(bot)
            expect(200, issues + '/' + ia['id'], {'title': 'bot allowed'}, bot_token, 'PATCH')
            status, _ = call(issues + '/' + ib['id'], {'title': 'bot denied'}, bot_token, 'PATCH')
            assert status in (400, 403, 404)
            expect(400, members + '/' + bot['id'], {'editor_teams': [finance]}, admin, 'PATCH')
            expect(200, members + '/' + alice['id'], {'editor_teams': []}, admin, 'PATCH')
            expect(403, issues + '/' + ia['id'], {'title': 'revoked'}, bot_token, 'PATCH')
            checks.append('personal bot inherits mixed grants, cannot exceed owner and loses write access when owner is narrowed')
            broad = person('legacy-editor', scope='all', mode='rw')
            reader = person('legacy-reader', scope='all', mode='ro')
            future = expect(200, '/api/collections/teams/records', {'key': 'FUT', 'name': 'Future'}, admin)['id']
            expect(200, issues, {'team': future, 'title': 'wildcard preserved', 'state': 'todo'}, token(broad))
            status, _ = call(issues, {'team': future, 'title': 'viewer denied', 'state': 'todo'}, token(reader))
            assert status in (400, 403, 404)
            future_roles = expect(200, '/api/lll/access', token=token(reader))['teams']
            assert any(t['id'] == future and t['role'] == 'viewer' for t in future_roles)
            checks.append('legacy all-team Editor and Viewer grants retain future-team semantics')
        finally:
            child.terminate()
            child.wait(timeout=30)
    receipt = {'result': 'pass', 'binary_sha256': hashlib.sha256(Path(binary).read_bytes()).hexdigest(), 'checks': checks}
    encoded = json.dumps(receipt, indent=2) + '\n'
    if args.report:
        args.report.write_text(encoded)
    print(encoded, end='')


if __name__ == '__main__':
    main()
