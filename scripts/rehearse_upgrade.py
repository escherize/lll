#!/usr/bin/env python3
"""Rehearse a server-first upgrade using explicit binaries and throwaway data.

No service URL or data-directory argument exists: this cannot target a user's
running board. It does not download binaries, modify installed tools or tag a
release. The two binaries must support the 1.x covered CLI surface.
"""
import argparse
import hashlib
import datetime
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request

from board_startup import wait_for_endpoints


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--after', required=True, type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    before, after = args.before.resolve(), args.after.resolve()
    for binary in (before, after):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            parser.error('both binaries must be executable files')
    report = {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'format': 1, 'scope': 'isolated 1.x client/server protocol and migration rehearsal', 'pairs': []}
    with tempfile.TemporaryDirectory(prefix='lll-upgrade-rehearsal-') as directory:
        root = Path(directory)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
        env.update(HOME=str(root), USER='upgrade-owner', LLL_BIND='127.0.0.1', LLL_TEAM='UPG',
                   LLL_BOARD_TOKEN='upgrade-rehearsal-board', LLL_ADMIN_EMAIL='upgrade@example.invalid',
                   LLL_ADMIN_PASSWORD='upgrade-rehearsal-password')

        def identity(binary):
            version = subprocess.check_output([str(binary), '--version'], cwd=root, env=env, text=True).strip()
            return {'version': version, 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}

        report['before'], report['after'] = identity(before), identity(after)
        child = None
        api, token = '', ''

        def stop():
            nonlocal child
            if child is not None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
                child = None

        def start(binary, data, name):
            nonlocal child, api
            current = dict(env, LLL_URL=f'http://127.0.0.1:{free_port()}')
            log = root / (name + '.log')
            with log.open('w') as output:
                child = subprocess.Popen([str(binary), 'up', '--no-open', '--pb-dir', str(data), '--port', str(free_port())],
                    cwd=root, env=current, stdout=output, stderr=subprocess.STDOUT)
            api = wait_for_endpoints(log)['db_url']
            assert child.poll() is None, 'isolated server exited during startup'

        def request(path, body=None, auth=None):
            req = urllib.request.Request(api + path, data=None if body is None else json.dumps(body).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (token if auth is None else auth)})
            try:
                response = urllib.request.urlopen(req, timeout=15)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)

        def cli(binary, *argv, code=0):
            current = {k: v for k, v in env.items() if not k.startswith('LLL_')}
            current.update(LLL_URL=api, LLL_TEAM='UPG', LLL_TOKEN=token)
            result = subprocess.run([str(binary), *argv], cwd=root, env=current, capture_output=True, text=True, timeout=40)
            assert result.returncode == code, (argv, result.returncode, result.stdout, result.stderr)
            return result.stdout, result.stderr

        try:
            data = root / 'data'
            start(before, data, 'before')
            status, auth = request('/api/collections/_superusers/auth-with-password',
                {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']}, '')
            assert status == 200, 'fixture administrator could not authenticate'
            admin = auth['token']
            status, members = request('/api/collections/members/records', auth=admin)
            assert status == 200
            owner = next(m for m in members['items'] if m['name'] == 'upgrade-owner')
            status, auth = request('/api/collections/members/impersonate/' + owner['id'], {'duration': 3600}, admin)
            assert status == 200
            token = auth['token']
            cli(before, 'project', 'create', 'Preserved project')
            cli(before, 'label', 'create', 'preserved-label')
            raw, _ = cli(before, 'issue', 'create', '-t', 'Preserved issue', '-b', 'Preserved body',
                         '--project', 'Preserved project', '--label', 'preserved-label', '--json')
            original = json.loads(raw)
            key = original['key']
            cli(before, 'issue', 'comment', key, '-b', 'Before upgrade')
            cli(before, 'issue', 'claim', key, '--agent', 'upgrade-worker')

            def verify(client, server_label):
                raw, _ = cli(client, 'issue', 'view', key, '--json')
                view = json.loads(raw)
                assert view['id'] == original['id'] and view['title'] == original['title']
                assert view['description'] == original['description'] and view['project'] == original['project']
                assert view['labels'] == original['labels'] and view['creator'] == original['creator']
                assert view['claim']['member'] == owner['id'] and view['claim']['agent'] == 'upgrade-worker'
                assert any(c['body'] == 'Before upgrade' and c['author'] == owner['id'] for c in view['comments'])
                listed, _ = cli(client, 'issue', 'list', '--json')
                assert any(i['id'] == original['id'] for i in json.loads(listed)['items'])
                report['pairs'].append({'client': 'before' if client == before else 'after', 'server': server_label,
                                        'checks': 'covered read fields, relations, authentication, claim and comment preserved', 'result': 'pass'})
                return view

            verify(before, 'before')
            verify(after, 'before')
            support_status, _ = request('/api/lll/comments/idempotency')
            if support_status == 404:
                count = len(json.loads(cli(after, 'issue', 'view', key, '--json')[0])['comments'])
                _, error = cli(after, 'issue', 'comment', key, '-b', 'Never sent', '--idempotency-key', 'probe', code=1)
                assert 'upgrade the server' in error
                assert len(json.loads(cli(after, 'issue', 'view', key, '--json')[0])['comments']) == count
                report['old_server_keyed_comment'] = 'safe refusal; no write'
            else:
                assert support_status == 200
                report['old_server_keyed_comment'] = 'supported by baseline'
            if '--activity' in cli(after, 'webhook', 'add', '--help')[0]:
                status, baseline_hooks = request('/api/collections/webhooks/records')
                assert status == 200
                capability, _ = request('/api/lll/activity')
                if capability == 404:
                    _, error = cli(after, 'webhook', 'add', 'http://127.0.0.1:1/rehearsal', '--secret', '', '--activity', code=1)
                    assert 'upgrade the server' in error
                    status, unchanged = request('/api/collections/webhooks/records')
                    assert status == 200 and unchanged['totalItems'] == baseline_hooks['totalItems']
                    report['old_server_activity_webhook'] = 'safe refusal; no registration'
                else:
                    assert capability == 200
                    report['old_server_activity_webhook'] = 'supported by baseline'
            stop()
            # A stopped copy includes the consistent SQLite database, WAL and
            # embedded migration state. Never restore by downgrading migrated data.
            snapshot = root / 'stopped-backup'
            shutil.copytree(data, snapshot)
            start(after, data, 'after')
            verify(before, 'after')
            verify(after, 'after')
            status, support = request('/api/lll/comments/idempotency')
            assert status == 200 and support.get('supported') is True
            argv = ('issue', 'comment', key, '-b', 'Retried after upgrade', '--idempotency-key', 'upgrade-comment', '--json')
            first = json.loads(cli(after, *argv)[0])
            second = json.loads(cli(after, *argv)[0])
            assert first['id'] == second['id'] and second.get('reused') is True
            cli(before, 'issue', 'comment', key, '-b', 'Old client still writes')
            report['new_server_keyed_comment'] = 'one comment on retry; old client unkeyed write works'
            stop()
            restored = root / 'restored-data'
            shutil.copytree(snapshot, restored)
            start(before, restored, 'restored-before')
            view = verify(before, 'restored-before')
            assert [c['body'] for c in view['comments']] == ['Before upgrade']
            report['restore'] = 'old binary starts stopped pre-upgrade backup; original member token works; post-backup writes absent'
            report['result'] = 'pass'
        finally:
            stop()
    encoded = json.dumps(report, indent=2) + '\n'
    if args.report:
        args.report.write_text(encoded)
    print(encoded, end='')


if __name__ == '__main__':
    main()
