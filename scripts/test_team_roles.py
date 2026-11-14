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
            for field, value in [('editor_teams+', [finance]), ('workspace_role', 'admin'), ('workspace_role+', 'admin')]:
                status, _ = call(members + '/' + alice['id'], {field: value}, alice_token, 'PATCH')
                assert status in (400, 403, 404), ('self-escalation modifier', field, status)
            unchanged = expect(200, members + '/' + alice['id'], token=admin)
            assert unchanged['editor_teams'] == [eng] and unchanged['workspace_role'] == 'member'
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

            # Workspace responsibility is independent of team-content grants.
            manager = person('workspace-admin', scope='teams', mode='ro', teams=[], workspace_role='admin')
            manager_token = token(manager)
            management = '/api/lll/permissions/'
            expect(403, '/api/lll/permissions', token=alice_token)
            expect(403, '/api/lll/permissions', token=token(broad))
            expect(200, '/api/lll/permissions', token=manager_token)
            expect(404, issues + '/' + ib['id'], token=manager_token)
            assert expect(200, '/api/lll/access', token=manager_token)['teams'] == []
            expect(200, '/api/collections/teams/records', {'key': 'ADM', 'name': 'Admin-created team'}, manager_token)
            # Ordinary provisioning by an explicit administrator defaults to no data.
            empty = expect(200, members, {'name': 'new-member', 'kind': 'person', 'email': 'new@local.invalid',
                'password': 'isolated-person-password', 'passwordConfirm': 'isolated-person-password'}, manager_token)
            assert empty['scope'] == 'teams' and empty['teams'] == [] and empty['mode'] == 'ro'
            assert empty['workspace_role'] == 'member'
            checks.append('explicit administration manages metadata without implicit private content; provisioning defaults to no team access')

            def cli(actor, *argv, code=0, stdin=None):
                current = dict(env, LLL_URL=api, LLL_TOKEN=actor)
                result = subprocess.run([binary, *argv], cwd=root, env=current, input=stdin,
                    capture_output=True, text=True, timeout=30)
                assert result.returncode == code, (argv, result.returncode, result.stdout, result.stderr)
                assert env['LLL_ADMIN_PASSWORD'] not in result.stdout + result.stderr
                return result

            observed = json.loads(cli(manager_token, 'member', 'permissions', empty['name'], '--json').stdout)
            cli_preview = json.loads(cli(manager_token, 'member', 'access', empty['name'], '--team', 'ENG',
                '--role', 'editor', '--preview', '--json').stdout)
            assert cli_preview['applied'] is False
            assert expect(200, members + '/' + empty['id'], token=admin)['editor_teams'] == []
            cli_applied = json.loads(cli(manager_token, 'member', 'access', empty['name'], '--team', 'ENG',
                '--role', 'editor', '--revision', observed['revision'], '--json').stdout)
            assert cli_applied['applied'] is True and cli_applied['event_id']
            stale = cli(manager_token, 'member', 'access', empty['name'], '--team', 'ENG', '--role', 'viewer',
                '--revision', observed['revision'], code=4)
            assert 'permissions changed' in stale.stderr.lower()
            cli(manager_token, 'member', 'access', empty['name'], '--role', 'editor', '--workspace-role', 'admin', code=2)
            # Inherited operator credentials must not elevate a configured member.
            refused = cli(alice_token, 'member', 'permissions', empty['name'], code=4)
            assert 'workspace administrator' in refused.stderr.lower()
            explicit = cli(alice_token, 'member', 'access', empty['name'], '--workspace-role', 'admin', '--preview',
                '--json', '--admin-email', env['LLL_ADMIN_EMAIL'], '--admin-password', '-',
                stdin=env['LLL_ADMIN_PASSWORD'] + '\n')
            assert json.loads(explicit.stdout)['after']['workspace_role'] == 'admin'
            assert expect(200, members + '/' + empty['id'], token=admin)['workspace_role'] == 'member'
            checks.append('CLI reads roles, previews/applies revision-bound changes, refuses stale or ambiguous commands and uses operator credentials only explicitly')

            def change(target, actor, **operation):
                snapshot = expect(200, management + target['id'], token=actor)
                return expect(200, management + target['id'], {'revision': snapshot['revision'], **operation}, actor)

            events_path = '/api/collections/permission_events/records'
            def event_count():
                return expect(200, events_path, token=admin)['totalItems']
            snapshot = expect(200, management + manager['id'], token=manager_token)
            expect(409, management + manager['id'], {'revision': snapshot['revision'], 'workspace_role': 'member'}, manager_token)
            snapshot = expect(200, management + alice['id'], token=manager_token)
            count = event_count()
            preview = expect(200, management + alice['id'], {'revision': snapshot['revision'], 'team': eng,
                'role': 'editor', 'preview': True}, manager_token)
            assert preview['applied'] is False and event_count() == count
            applied = expect(200, management + alice['id'], {'revision': snapshot['revision'], 'team': eng,
                'role': 'editor'}, manager_token)
            assert applied['applied'] is True and applied['event_id']
            assert event_count() == count + 1
            expect(409, management + alice['id'], {'revision': snapshot['revision'], 'team': finance,
                'role': 'editor'}, manager_token)
            assert event_count() == count + 1
            event = expect(200, events_path + '/' + applied['event_id'], token=manager_token)
            assert event['actor'] == manager['id'] and event['actor_kind'] == 'person'
            assert event['member'] == alice['id'] and 'editor_teams' in event['changes']
            expect(403, events_path, {'member': alice['id'], 'actor_kind': 'system'}, admin)
            status, _ = call(events_path + '/' + applied['event_id'], {'changes': {}}, admin, 'PATCH')
            assert status in (400, 403), status
            assert expect(200, events_path, token=alice_token)['items'] == []
            checks.append('preview is side-effect free; apply is revision-bound and audited; stale, forged and rewritten history refused')
            # Role promotion preserves the exact data grant and cannot promote bots.
            before_grants = expect(200, members + '/' + alice['id'], token=admin)
            promotion = change(alice, manager_token, workspace_role='admin')
            after_grants = expect(200, members + '/' + alice['id'], token=admin)
            assert promotion['after']['workspace_role'] == 'admin'
            assert all(before_grants[k] == after_grants[k] for k in ['scope', 'teams', 'mode', 'editor_teams'])
            bot_snapshot = expect(200, management + bot['id'], token=manager_token)
            expect(400, management + bot['id'], {'revision': bot_snapshot['revision'], 'workspace_role': 'admin'}, manager_token)
            expect(400, members + '/' + bot['id'], {'workspace_role': 'admin'}, admin, 'PATCH')
            change(alice, manager_token, workspace_role='member')
            # Self-grants are explicit and leave the same audit evidence.
            self_grant = change(manager, manager_token, team=finance, role='viewer')
            assert self_grant['event_id']
            expect(200, issues + '/' + ib['id'], token=manager_token)
            status, _ = call(issues + '/' + ib['id'], {'title': 'admin viewer denied'}, manager_token, 'PATCH')
            assert status in (400, 403, 404)
            checks.append('role changes preserve data grants, bot promotion is refused, and private-team self-grants are explicit and audited')
            snapshot = expect(200, management + broad['id'], token=manager_token)
            operation = {'revision': snapshot['revision'], 'team': finance, 'role': 'viewer'}
            refused = expect(400, management + broad['id'], operation, manager_token)
            assert refused['data']['code'] == 'confirm_all_team_conversion'
            count = event_count()
            conversion = expect(200, management + broad['id'], {**operation, 'convert_all_teams': True, 'preview': True}, manager_token)
            assert conversion['future_team_access_lost'] is True and event_count() == count
            converted = expect(200, management + broad['id'], {**operation, 'convert_all_teams': True}, manager_token)
            assert converted['future_team_access_lost'] is True and converted['after']['all'] is False
            new_team = expect(200, '/api/collections/teams/records', {'key': 'NEW', 'name': 'Created after conversion'}, admin)['id']
            new_issue = expect(200, issues, {'team': new_team, 'title': 'new', 'state': 'todo'}, admin)
            expect(404, issues + '/' + new_issue['id'], token=token(broad))
            checks.append('all/future-team conversion requires explicit confirmation and accurately previews the loss of future coverage')
            # Revoked managers cannot use an old token to change another grant.
            snapshot = expect(200, management + alice['id'], token=manager_token)
            expect(200, members + '/' + manager['id'], {'workspace_role': 'member'}, admin, 'PATCH')
            expect(403, management + alice['id'], {'revision': snapshot['revision'], 'team': finance,
                'role': 'editor'}, manager_token)
            checks.append('revoked administration is checked afresh and cannot mutate grants using an existing token')
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
