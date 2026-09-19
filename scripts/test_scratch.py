#!/usr/bin/env python3
"""Installed-binary scratch boot from a poisoned, unrelated directory."""
import hashlib
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
binary = root / 'target/.lisette/bin/lll'

for flag in ('--scratch', '--local'):
    with tempfile.TemporaryDirectory(prefix='lll-scratch-test-') as directory:
        base = Path(directory)
        caller = base / 'unrelated-work'
        caller.mkdir()
        repo = caller / '.lll.toml'
        repo.write_text('url = "https://hosted.example.invalid"\nteam = "REMOTE"\n')
        home = base / 'home'
        config = home / '.config/lll/lll.toml'
        config.parent.mkdir(parents=True)
        config.write_text('url = "https://hosted.example.invalid"\ntoken = "fixture-hosted-token"\n')
        xdg = base / 'xdg/lll/lll.toml'
        xdg.parent.mkdir(parents=True)
        xdg.write_text('token = "fixture-xdg-token"\n')
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (repo, config, xdg)}
        env = dict(os.environ, HOME=str(home), TMPDIR=directory,
                   XDG_CONFIG_HOME=str(base / 'xdg'),
                   LLL_CONFIG_HOME=str(base / 'xdg'),
                   LLL_TOKEN='fixture-env-token', LLL_URL='https://hosted.example.invalid',
                   LLL_TEAM='REMOTE', LLL_WEB_URL='https://invalid.example',
                   LLL_ADMIN_EMAIL='wrong@example.com', LLL_ADMIN_PASSWORD='wrong-password',
                   LLL_BOARD_TOKEN='fixture-inherited-board-token', LLL_BIND='203.0.113.9',
                   LC_ALL='C')
        log_path = base / 'boot.log'
        with log_path.open('w') as log:
            process = subprocess.Popen([str(binary), 'up', flag, '--no-open'],
                                       cwd=caller, env=env, stdout=log, stderr=log,
                                       start_new_session=True)
        db = web = 0
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                output = log_path.read_text()
                if 'board  login ' in output:
                    break
                assert process.poll() is None, 'scratch exited before startup: ' + output
                time.sleep(.1)
            else:
                raise AssertionError('scratch did not start: ' + output)
            db_match = re.search(r'^api    http://127\.0\.0\.1:(\d+)$', output, re.M)
            web_match = re.search(r'^board  http://127\.0\.0\.1:(\d+)$', output, re.M)
            scratch_match = re.search(r'^scratch data   (.+)$', output, re.M)
            admin_match = re.search(r'^scratch admin  ([^ ]+) / ([^ ]+) \(shown once\)$', output, re.M)
            assert db_match and web_match and scratch_match and admin_match, 'scratch banner incomplete'
            db, web = int(db_match[1]), int(web_match[1])
            scratch = Path(scratch_match[1])
            assert scratch.resolve().is_relative_to(base.resolve()), 'scratch data escaped temp root'
            assert (scratch / 'pb_data/data.db').exists(), 'scratch database missing'
            assert not (scratch / '.lll.toml').exists(), 'scratch wrote a repo config'
            assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest
                       for p, digest in before.items()), 'caller config changed'
            assert 'fixture-inherited-board-token' not in output
            assert 'hosted.example.invalid' not in output
            assert 'wrong@example.com' not in output
            cli_env = {k: v for k, v in env.items() if not k.startswith('LLL_')}
            cli_env['LLL_CONFIG_HOME'] = str(scratch / 'config')
            identity = subprocess.run([str(binary), 'whoami'], cwd=scratch, env=cli_env,
                                      capture_output=True, text=True, timeout=5)
            assert identity.returncode == 0 and 'scratch' in identity.stdout, identity.stderr
            teams = subprocess.run([str(binary), 'team', 'list'], cwd=scratch, env=cli_env,
                                   capture_output=True, text=True, timeout=5)
            assert teams.returncode == 0 and 'SCRAT' in teams.stdout, teams.stderr
            admin_email, admin_password = admin_match.groups()
            request = urllib.request.Request(
                f'http://127.0.0.1:{db}/api/collections/_superusers/auth-with-password',
                data=json.dumps({'identity': admin_email, 'password': admin_password}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=3) as response:
                assert json.load(response)['token'], 'generated admin pair cannot log in'
            login = re.search(r'board  login (http://\S+)', output).group(1)
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with opener.open(login, timeout=3) as response:
                assert response.status == 200 and 'board_token' not in response.url
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
    print(f'{flag}: poisoned config ignored; CLI, browser, admin and shutdown verified')
