#!/usr/bin/env python3
"""LLL-445: board/CLI authorship and renewal follow the member token."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from board_startup import wait_for_board

binary = str(Path(sys.argv[1]).resolve())


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


with tempfile.TemporaryDirectory(prefix='lll-445-') as directory:
    base = Path(directory)
    config = base / 'config/lll/lll.toml'
    config.parent.mkdir(parents=True)
    config.write_text('token = "stale.hosted.token"\nme = "legacy-ghost"\n')
    db, web = port(), port()
    url = f'http://127.0.0.1:{db}'
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
    env.update(LLL_CONFIG_HOME=str(base / 'config'), LLL_URL=url,
               LLL_TEAM='IDENT', LLL_BOARD_TOKEN='identity-fixture',
               LLL_ME='env-ghost', USER='board-owner',
               LLL_ADMIN_EMAIL='admin@local.dev', LLL_ADMIN_PASSWORD='admin-local-123')
    processes = []

    def api(path, payload=None, token='', form=False, board=web, method=None):
        endpoint = f'http://127.0.0.1:{board}' if form else url
        data = None if payload is None else (
            urllib.parse.urlencode(payload).encode() if form else json.dumps(payload).encode())
        headers = {'Cookie': 'lll_board=identity-fixture'} if form else {}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        if data is not None:
            headers['Content-Type'] = ('application/x-www-form-urlencoded' if form else 'application/json')
        with urllib.request.urlopen(urllib.request.Request(endpoint + path, data=data, headers=headers, method=method), timeout=10) as response:
            body = response.read().decode()
            return body if form else json.loads(body)

    def cli(*args, **overrides):
        return subprocess.run([binary, *args], cwd=base, env=dict(env, **overrides),
                              text=True, capture_output=True, timeout=15)

    def boot(name, settings, board_port, demo=False):
        log = base / f'{name}.log'
        with log.open('w') as output:
            process = subprocess.Popen([binary, 'up', '--no-open', '--port', str(board_port),
                                        '--pb-dir', str(base / 'data')] + (['--demo'] if demo else []), cwd=base, env=settings,
                                       stdout=output, stderr=output, start_new_session=True)
        processes.append(process)
        wait_for_board(log, f'http://127.0.0.1:{board_port}')
        return log.read_text()

    try:
        output = boot('bootstrap', env, web)
        assert 'member board-owner' in output, output
        assert 'superuser credentials instead' in output, output
        assert 'stale.hosted.token' in config.read_text(), 'up overwrote an existing CLI credential'
        effective = cli('config', '--list')
        assert effective.returncode == 0 and '\tme=' not in effective.stdout, effective
        removed = cli('config', 'set', 'me', 'someone')
        assert removed.returncode != 0 and 'supported keys: url, web_url' in removed.stderr, removed
        api('/t/IDENT/', form=True)  # empty list caches the boot credential's successful probe
        admin = api('/api/collections/_superusers/auth-with-password',
                    {'identity': 'admin@local.dev', 'password': 'admin-local-123'})['token']
        members = api('/api/collections/members/records', token=admin)['items']
        owner = next(m for m in members if m['name'] == 'board-owner')
        assert not any(m['name'] in ('legacy-ghost', 'env-ghost') for m in members)
        owner_token = api(f'/api/collections/members/impersonate/{owner["id"]}',
                          {'duration': 3600}, admin)['token']
        identity = cli('whoami', LLL_TOKEN=owner_token)
        assert identity.returncode == 0 and 'board-owner <' in identity.stdout, identity
        assert 'token   env:LLL_TOKEN' in identity.stdout, identity.stdout
        created = cli('issue', 'create', '-t', 'Member authorship', '--json', LLL_TOKEN=owner_token)
        assert created.returncode == 0, created
        issue = json.loads(created.stdout)
        assert issue['creator'] == owner['id'], issue
        key = f'IDENT-{issue["number"]}'
        api('/comment', {'key': key, 'body': 'Bootstrap board author'}, form=True)
        comments = api('/api/collections/comments/records', token=admin)['items']
        assert next(c for c in comments if c['body'] == 'Bootstrap board author')['author'] == owner['id']

        # A valid member token is authoritative even with another USER, legacy
        # me, and unusable admin credentials; startup must not need the admin.
        second = api('/api/collections/members/records',
                     {'name': 'chosen-member', 'email': 'chosen@lll.test',
                      'password': 'chosen-password-123', 'passwordConfirm': 'chosen-password-123'}, admin)
        chosen = api(f'/api/collections/members/impersonate/{second["id"]}', {'duration': 3600}, admin)['token']
        other_web = port()
        output = boot('provided-member', dict(env, LLL_TOKEN=chosen, USER='do-not-seed',
                      LLL_ADMIN_EMAIL='wrong@lll.test', LLL_ADMIN_PASSWORD='wrong-password'), other_web)
        assert 'member chosen-member' in output, output
        api('/comment', {'key': key, 'body': 'Provided token author'}, form=True, board=other_web)
        comments = api('/api/collections/comments/records', token=admin)['items']
        assert next(c for c in comments if c['body'] == 'Provided token author')['author'] == second['id']
        assert not any(m['name'] == 'do-not-seed' for m in api('/api/collections/members/records', token=admin)['items'])

        # A real board that has cached a successful probe must also recover
        # when a password reset revokes its member token during the process.
        stream_log = base / 'identity-events.log'
        with stream_log.open('w') as stream_output:
            stream = subprocess.Popen(['curl', '-sN', '-H', 'Cookie: lll_board=identity-fixture',
                                       f'http://127.0.0.1:{web}/events?page=issue&key={key}'],
                                      stdout=stream_output, stderr=subprocess.DEVNULL,
                                      start_new_session=True)
        processes.append(stream)
        deadline = time.monotonic() + 10
        while 'issue-detail' not in stream_log.read_text() and time.monotonic() < deadline:
            time.sleep(.1)
        assert 'issue-detail' in stream_log.read_text(), 'issue stream did not register'
        api(f'/api/collections/members/records/{owner["id"]}',
            {'password': 'reset-owner-password-123', 'passwordConfirm': 'reset-owner-password-123'},
            admin, method='PATCH')
        api('/comment', {'key': key, 'body': 'Revoked board author'}, form=True)
        comments = api('/api/collections/comments/records', token=admin)['items']
        assert next(c for c in comments if c['body'] == 'Revoked board author')['author'] == owner['id']
        deadline = time.monotonic() + 10
        while 'Revoked board author' not in stream_log.read_text() and time.monotonic() < deadline:
            time.sleep(.1)
        assert 'Revoked board author' in stream_log.read_text(), 'renewal did not restore live comments'
        assert 'id="comments"' in stream_log.read_text(), stream_log.read_text()

        # Bootstrap still has an identity when USER is absent. A configured
        # superuser token is enough even when the default admin pair is wrong.
        local_web = port()
        output = boot('missing-user', dict(env, USER='', LLL_TOKEN=admin,
                      LLL_ADMIN_EMAIL='wrong@lll.test', LLL_ADMIN_PASSWORD='wrong-password'), local_web)
        assert 'member local' in output, output
        local_member = next(m for m in api('/api/collections/members/records', token=admin)['items'] if m['name'] == 'local')
        api('/comment', {'key': key, 'body': 'Missing USER author'}, form=True, board=local_web)
        comments = api('/api/collections/comments/records', token=admin)['items']
        assert next(c for c in comments if c['body'] == 'Missing USER author')['author'] == local_member['id']

        # Demo seeding also preserves a pre-existing file credential; the
        # original source must be captured before boot sets LLL_TOKEN.
        demo_web = port()
        output = boot('demo-existing-login', dict(env, LLL_TEAM='KEEPDEMO'), demo_web, demo=True)
        assert 'seeded KEEPDEMO' in output and 'CLI keeps its configured token' in output, output
        assert 'stale.hosted.token' in config.read_text(), 'demo overwrote the existing CLI login'

        # The same read/write recovery used by the board must resolve and mint
        # the same member after expiry, including the actor lookup itself.
        short = api(f'/api/collections/members/impersonate/{owner["id"]}', {'duration': 1}, admin)['token']
        time.sleep(2)
        renewed = cli('issue', 'comment', key, '-b', 'Renewed member author',
                      LLL_TOKEN=short, LLL_REMINT='1', LLL_REMINT_MEMBER=owner['id'])
        assert renewed.returncode == 0 and 'as board-owner' in renewed.stdout, renewed
        comments = api('/api/collections/comments/records', token=admin)['items']
        assert next(c for c in comments if c['body'] == 'Renewed member author')['author'] == owner['id']
        print('Board identity: bootstrap, supplied member, legacy config, CLI source, web authorship, revocation, missing USER, and renewal verified')
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
