#!/usr/bin/env python3
"""LLL-648: the README's first run, from an empty HOME with no flags but ports.

A plain loopback `lll up` (no --pb-dir: that is a throwaway and leaves the CLI
alone) prints the fallback administrator pair, logs the CLI in as its member
and saves the board login link, so the next commands work with no login step.
An invited member then replaces its temporary password itself, with no
administrator. A second home holding another server's url keeps it.
"""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

binary = str(Path(sys.argv[1]).resolve())


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def clean_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(home), LC_ALL='C', USER='firstrun')
    return env


def boot(directory, env, log):
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port())], cwd=directory, env=env,
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        text = log.read_text()
        if 'board  login ' in text:
            return child, text
        assert child.poll() is None, 'lll up exited: ' + text
        time.sleep(.1)
    child.terminate()
    raise AssertionError('lll up did not start: ' + log.read_text())


def run(directory, env, *argv, stdin=None):
    return subprocess.run([binary, *argv], cwd=directory, env=env, input=stdin, text=True,
                          capture_output=True, timeout=30)


with tempfile.TemporaryDirectory(prefix='lll-first-run-') as tmp:
    root = Path(tmp)
    home, board_dir = root / 'home', root / 'home' / 'my-board'
    board_dir.mkdir(parents=True)
    env = clean_env(home)
    api = f'http://127.0.0.1:{port()}'
    child, banner = boot(board_dir, dict(env, LLL_TEAM='FIRST', LLL_URL=api), root / 'up.log')
    try:
        assert re.search(r'^admin  admin@local\.dev; generated password in \S+/\.lll-admin\.json ', banner, re.M), banner
        assert 'admin-local-123' not in banner, banner
        config = home / '.config' / 'lll' / 'lll.toml'
        assert f'\ncli    logged in as firstrun; url and token saved to {config}\n' in banner, banner
        saved = config.read_text()
        assert f'url = "{api}"' in saved and 'token = "' in saved, saved
        login = re.search(r'^board  login (\S+)', banner, re.M).group(1)
        assert oct((config.parent / 'board-login-url').stat().st_mode & 0o777) == '0o600'

        # The second shell: no LLL_* at all, straight to work.
        for argv, want in [(('whoami',), 'firstrun'),
                           (('issue', 'create', '-t', 'First issue', '--priority', '2'), 'FIRST-1'),
                           (('issue', 'claim', 'FIRST-1'), 'Claimed'),
                           (('issue', 'comment', 'FIRST-1', '-b', 'Started on it'), 'Commented'),
                           (('issue', 'close', 'FIRST-1'), 'Closed'),
                           (('board',), login)]:
            out = run(board_dir, env, *argv)
            assert out.returncode == 0 and want in out.stdout, (argv, out.stdout + out.stderr)

        # An invite's temporary password, replaced by the member itself.
        out = run(board_dir, env, 'member', 'invite', 'kim', '--email', 'kim@example.com', '--team', 'FIRST')
        assert out.returncode == 0, out.stdout + out.stderr
        temp = re.search(r'temporary password: (\S+)', out.stdout).group(1)
        assert f'lll member set-password kim --old-password {temp}' in out.stdout, out.stdout
        assert '/t/FIRST/?board_token=' in out.stdout, out.stdout
        kim_dir = root / 'kim'
        kim_dir.mkdir()
        kim = clean_env(root / 'kim-home')
        out = run(kim_dir, kim, 'login', '--url', api, '--email', 'kim@example.com', '--password', temp)
        assert out.returncode == 0, out.stdout + out.stderr
        out = run(kim_dir, kim, 'member', 'set-password', 'firstrun', '--old-password', temp, '--password', 'x' * 12)
        assert out.returncode != 0 and 'not firstrun' in out.stderr, out.stdout + out.stderr
        out = run(kim_dir, kim, 'member', 'set-password', 'kim', '--old-password', 'wrong-password', '--password', 'x' * 12)
        assert out.returncode != 0 and 'nothing changed' in out.stderr, out.stdout + out.stderr
        kim_config = root / 'kim-home' / '.config' / 'lll' / 'lll.toml'
        old_token = re.search(r'token = "([^"]+)"', kim_config.read_text()).group(1)
        out = run(kim_dir, kim, 'member', 'set-password', 'kim', '--old-password', temp, '--password', 'kims-own-pw')
        assert out.returncode == 0 and 'new token saved' in out.stdout, out.stdout + out.stderr
        # LLL-679: the change revoked the old token. Using it is not
        # authenticated (exit 6), not "an administrator token" at exit 1.
        out = run(kim_dir, dict(kim, LLL_TOKEN=old_token),
                  'member', 'set-password', 'kim', '--old-password', 'kims-own-pw', '--password', 'y' * 12)
        assert out.returncode == 6 and 'was rejected' in out.stderr, (out.returncode, out.stderr)
        assert 'administrator' not in out.stderr, out.stderr
        # An administrator's token still gets the --old-password advice. The
        # password is the generated one the banner names (LLL-676).
        admin_file = re.search(r'generated password in (\S+/\.lll-admin\.json) ', banner).group(1)
        admin_pw = json.loads(Path(admin_file).read_text())['password']
        req = urllib.request.Request(f'{api}/api/collections/_superusers/auth-with-password',
                                     data=json.dumps({'identity': 'admin@local.dev',
                                                      'password': admin_pw}).encode(),
                                     headers={'Content-Type': 'application/json'})
        admin_token = json.load(urllib.request.urlopen(req))['token']
        out = run(kim_dir, dict(kim, LLL_TOKEN=admin_token),
                  'member', 'set-password', 'kim', '--old-password', 'kims-own-pw', '--password', 'y' * 12)
        assert out.returncode == 1 and "is an administrator's" in out.stderr, (out.returncode, out.stderr)
        out = run(kim_dir, kim, 'whoami')
        assert out.returncode == 0 and 'kim' in out.stdout, out.stdout + out.stderr
        out = run(kim_dir, kim, 'login', '--email', 'kim@example.com', '--password', temp)
        assert out.returncode != 0, 'the temporary password still works'
        out = run(kim_dir, kim, 'login', '--email', 'kim@example.com', '--password', 'kims-own-pw')
        assert out.returncode == 0, out.stdout + out.stderr
    finally:
        os.killpg(child.pid, 15)
        child.wait(timeout=15)

    # A logged-out home pointed at a hosted board keeps its url.
    other = root / 'other-home'
    (other / '.config' / 'lll').mkdir(parents=True)
    hosted = other / '.config' / 'lll' / 'lll.toml'
    hosted.write_text('url = "https://hosted.example.invalid"\n')
    other_dir = root / 'other'
    other_dir.mkdir()
    child, banner = boot(other_dir, dict(clean_env(other), LLL_TEAM='OTHER', LLL_URL=f'http://127.0.0.1:{port()}'),
                         root / 'up2.log')
    try:
        assert 'cli    not logged in to this board: the home config points the CLI at https://hosted.example.invalid' \
            in banner, banner
        assert 'token' not in hosted.read_text() and 'hosted.example.invalid' in hosted.read_text()
    finally:
        os.killpg(child.pid, 15)
        child.wait(timeout=15)

print('first run: README walk, CLI auto-login, own password change and a kept hosted url passed')
