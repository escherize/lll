#!/usr/bin/env python3
"""Check the default and opted-in administration surface through lll up."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as response:
        return response.code, response.read()


for admin_ui in (False, True):
    with tempfile.TemporaryDirectory(prefix='lll-server-surface-') as directory:
        root = Path(directory)
        home = root / 'home'
        home.mkdir()
        db_port, web_port = free_port(), free_port()
        while web_port == db_port:
            web_port = free_port()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
        env.update(HOME=str(home), LLL_CONFIG_HOME=str(home / '.config'),
                   XDG_CONFIG_HOME=str(home / '.config'),
                   LLL_URL=f'http://127.0.0.1:{db_port}', LLL_TEAM='SURF',
                   LLL_BIND='127.0.0.1', USER='surfaceprobe',
                   LLL_ADMIN_EMAIL='surface-admin@example.invalid',
                   LLL_ADMIN_PASSWORD='throwaway-surface-admin',
                   LLL_BOARD_TOKEN='throwaway-surface-board')
        log = root / 'up.log'
        args = [binary, 'up', '--no-open', '--pb-dir', str(root / 'data'),
                '--port', str(web_port)]
        if admin_ui:
            args.append('--admin-ui')
        with log.open('w') as output:
            child = subprocess.Popen(args, cwd=root, env=env, stdout=output,
                                     stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    text = log.read_text()
                    assert child.poll() is None, text
                    if f'board  http://127.0.0.1:{web_port}' in text:
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError('board readiness timed out: ' + log.read_text())
                # A listener is bound before the banner; it begins serving just after.
                base = f'http://127.0.0.1:{web_port}'
                announced = wait_for_endpoints(log, timeout=5)
                assert announced['db_url'] == env['LLL_URL']
                assert announced['board_url'] == base
                assert announced['board_token'] == env['LLL_BOARD_TOKEN']
                assert get(base + '/')[0] == 401
                assert get(base + '/api/health')[0] == 200
                for path in ('/_', '/_/', '/_/assets/fixture-missing.js'):
                    status, body = get(base + path)
                    if admin_ui:
                        if path in ('/_', '/_/'):
                            assert status == 200 and b'PocketBase' in body, (path, status)
                    else:
                        assert status == 404 and b'PocketBase' not in body, (path, status)
                text = log.read_text()
                assert 'throwaway-surface-admin' not in text, text
                assert 'surface-admin@example.invalid' not in text, text
                assert 'PocketBase' not in text, text
                assert ('\nadmin  ' in text) == admin_ui, text
                if admin_ui:
                    assert base + '/_/' in text and '--admin-ui' in text, text
                else:
                    assert '/_/' not in text, text
                for command in ([], ['up'], ['api'], ['config'], ['login'],
                                ['member'], ['token'], ['watch'], ['issue'], ['doc']):
                    help_result = subprocess.run([binary, *command, '--help'],
                                                 cwd=root, env=env, text=True,
                                                 capture_output=True, timeout=10)
                    assert help_result.returncode == 0, help_result.stderr
                    assert 'pocketbase' not in (help_result.stdout + help_result.stderr).lower(), command
            finally:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
print('Server surface: default admin routes hidden; explicit opt-in works; API and board gate preserved; no admin credentials printed')
