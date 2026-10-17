#!/usr/bin/env python3
"""`lll new` beside another server's login (LLL-726).

The home config holds a login for another server (the hosted board). `lll new`
must leave the CLI in its directory talking to the new board, so `lll issue
create` there makes PAY-1, while every other directory keeps the other login
and the home config is not rewritten. The board's token goes to logins.toml
(0600), never to the committed .lll.toml.
"""
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

binary = str(Path(sys.argv[1]).resolve())
DEADLINE = 120


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


with tempfile.TemporaryDirectory(prefix='lll-new-cli-login-') as directory:
    root = Path(directory)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
    env.update(HOME=str(root / 'home'), LLL_CONFIG_HOME=str(root / 'config'))
    # The other server's login. Its explicit port is free, so the board's own
    # API (which starts from the configured port) never lands on 8090.
    hosted = f'http://hosted.invalid:{free_port()}'
    home = root / 'config/lll/lll.toml'
    home.parent.mkdir(parents=True)
    home_text = f'url = "{hosted}"\ntoken = "hosted-token"\nteam = "LLL"\n'
    home.write_text(home_text)
    home.chmod(0o600)
    work = root / 'work'
    elsewhere = root / 'elsewhere'
    work.mkdir()
    elsewhere.mkdir()

    def run(cwd, *args):
        result = subprocess.run([binary, *args], cwd=cwd, env=env, text=True,
                                capture_output=True, timeout=30)
        assert result.returncode == 0, f'{args}: {result.stdout}{result.stderr}'
        return result.stdout

    def boot(name):
        log = root / name
        with log.open('w') as handle:
            proc = subprocess.Popen(
                [binary, 'new', 'Payments rewrite', '--no-open', '--port', str(free_port())],
                cwd=work, env=env, stdout=handle, stderr=handle, start_new_session=True)
        started = time.monotonic()
        while time.monotonic() - started < DEADLINE:
            out = log.read_text()
            if 'board  http' in out:
                return proc, out
            if proc.poll() is not None:
                raise AssertionError(f'lll new exited early:\n{out}')
            time.sleep(0.1)
        os.killpg(proc.pid, signal.SIGTERM)
        raise AssertionError(f'lll new did not start:\n{log.read_text()}')

    def stop(proc):
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=30)

    # A directory attached to another team and server (a repo's committed
    # .lll.toml) is refused with exit 4, and nothing is written.
    attached = root / 'attached'
    attached.mkdir()
    attached_text = 'team = "LLL"\nurl = "https://lll.example.com"\n'
    (attached / '.lll.toml').write_text(attached_text)
    refused = subprocess.run([binary, 'new', 'Payments rewrite', '--no-open'],
                             cwd=attached, env=env, text=True, capture_output=True,
                             timeout=30)
    assert refused.returncode == 4, (refused.returncode, refused.stdout, refused.stderr)
    assert 'team LLL at https://lll.example.com' in refused.stderr, refused.stderr
    assert (attached / '.lll.toml').read_text() == attached_text
    assert not (root / 'config/lll/boards/pay').exists()

    proc, out = boot('new.log')
    try:
        assert 'cli    logged in here' in out, out
        created = json.loads(run(work, 'issue', 'create', '-t', 'hi', '--json'))
        assert created['key'] == 'PAY-1', created
        assert 'PAY-1' in run(work, 'issue', 'list')

        # The directory: url from .lll.toml, token from logins.toml.
        logins = root / 'config/lll/logins.toml'
        assert str(logins) in run(work, 'config', 'list')
        repo = (work / '.lll.toml').read_text()
        assert 'url = "http://127.0.0.1:' in repo, repo
        assert 'token' not in repo, repo
        assert stat.S_IMODE(logins.stat().st_mode) == 0o600, oct(logins.stat().st_mode)
        assert 'hosted-token' not in logins.read_text()

        # Everywhere else: the other login, untouched.
        assert home.read_text() == home_text, home.read_text()
        there = run(elsewhere, 'config', 'list')
        assert hosted in there, there
        assert str(home) in there, there
        assert str(logins) not in there, there
    finally:
        stop(proc)

    # Reopening the board keeps the directory logged in.
    proc, out = boot('reopen.log')
    try:
        assert 'open   Payments rewrite' in out, out
        created = json.loads(run(work, 'issue', 'create', '-t', 'again', '--json'))
        assert created['key'] == 'PAY-2', created
        assert home.read_text() == home_text, home.read_text()
    finally:
        stop(proc)

    # Logging out here removes this board's saved login and keeps the home
    # config's login for the other server.
    logins = root / 'config/lll/logins.toml'
    board_url = [l for l in (work / '.lll.toml').read_text().splitlines()
                 if l.startswith('url = ')][0].split('"')[1]
    out = run(work, 'logout')
    assert f'token for {board_url} cleared from {logins}' in out, out
    assert board_url not in logins.read_text()
    assert home.read_text() == home_text, home.read_text()
    assert 'token=' in run(elsewhere, 'config', 'list')
    print('lll new beside another login: ok')
