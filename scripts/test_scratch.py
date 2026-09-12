#!/usr/bin/env python3
"""Boot the scratch recipe with hostile inherited config and credentials."""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request

root = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix='lll-scratch-test-') as directory:
    base = Path(directory)
    config = base / 'home/.config/lll/lll.toml'
    config.parent.mkdir(parents=True)
    original = b'token = "fixture-hosted-token"\nme = "hosted-person"\n'
    config.write_bytes(original)
    env = dict(os.environ, HOME=str(base / 'home'), TMPDIR=directory,
               LLL_TOKEN='fixture-env-token', LLL_ME='hosted-person',
               LLL_URL='http://127.0.0.1:1', LLL_WEB_URL='https://invalid.example',
               LLL_ADMIN_EMAIL='wrong@example.com', LLL_ADMIN_PASSWORD='wrong-password',
               LLL_BOARD_TOKEN='fixture-inherited-board-token', LLL_BIND='203.0.113.9',
               LLL_TEAM='SCRATCH42', LC_ALL='C')
    log_path = base / 'boot.log'
    with log_path.open('w') as log:
        process = subprocess.Popen(['bash', 'scripts/scratch.sh', '--no-open'],
                                   cwd=root, env=env, stdout=log, stderr=log,
                                   start_new_session=True)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                output = log_path.read_text()
                if 'board  login ' in output:
                    break
                assert process.poll() is None, 'scratch exited before board startup'
                time.sleep(.1)
            else:
                raise AssertionError('scratch board did not start within 20 seconds')
            ports = re.search(r'scratch board: db :(\d+), web :(\d+), data (.+)', output)
            assert ports, 'scratch banner missing'
            db, web = map(int, ports.group(1, 2))
            scratch = Path(ports.group(3))
            assert scratch.resolve().is_relative_to(base.resolve()), 'scratch data escaped temporary root'
            assert config.read_bytes() == original, 'caller config changed'
            assert not (scratch / 'home/.lll.toml').exists(), 'scratch attached its cwd'
            assert (scratch / 'pb_data/data.db').exists(), 'scratch database missing'
            req = urllib.request.Request(
                f'http://127.0.0.1:{db}/api/collections/_superusers/auth-with-password',
                data=json.dumps({'identity': 'admin@local.dev', 'password': 'admin-local-123'}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=3) as response:
                token = json.load(response)['token']
            req = urllib.request.Request(f'http://127.0.0.1:{db}/api/collections/teams/records',
                                         headers={'Authorization': token})
            with urllib.request.urlopen(req, timeout=3) as response:
                teams = json.load(response)['items']
            assert [team['key'] for team in teams] == ['SCRATCH42'], 'explicit scratch team lost'
            login = re.search(r'board  login (http://\S+)', output).group(1)
            assert 'fixture-inherited-board-token' not in login, 'inherited board token reused'
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with opener.open(login, timeout=3) as response:
                assert response.status == 200, 'board login failed'
            assert 'hosted-person' not in output, 'inherited identity reused'
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for port in (db, web):
            with socket.socket() as connection:
                connection.settimeout(.5)
                assert connection.connect_ex(('127.0.0.1', port)) != 0, 'scratch listener survived shutdown'
print('Scratch: hostile home/env isolated, local admin and explicit team verified, listeners stopped')
