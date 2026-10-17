#!/usr/bin/env python3
"""LLL-721: a Homebrew lll older than its server updates itself in the background.

A copy of the built binary stands in a fake Homebrew Cellar, reached through a
bin/ symlink as Homebrew installs it. A stub `brew` first on PATH records its
arguments and takes two seconds, so the test sees lll return before the
upgrade ends. A stub discovery server advertises a newer version. Neither
Homebrew nor the network is touched.
"""
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

binary = Path(sys.argv[1]).resolve()
STUB_BODY = b'{"items":[],"totalItems":0,"page":1,"perPage":200}'
WARNING_END = 'Upgrade: lll upgrade'


def stub_server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            discovery = {'service': 'lll', 'web_url': '.', 'version': '99.0.0'}
            body = json.dumps(discovery).encode() if self.path == '/.well-known/lll' else STUB_BODY
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def homebrew_server_running():
    """A real Homebrew `lll up` on this machine switches auto-update off, by design."""
    out = subprocess.run(['ps', '-axo', 'args='], capture_output=True, text=True).stdout
    for line in out.splitlines():
        fields = line.split()
        if len(fields) > 1 and os.path.basename(fields[0]) == 'lll' and 'up' in fields[1:3]:
            exe = shutil.which(fields[0]) or fields[0]
            if '/Cellar/' in os.path.realpath(exe):
                return True
    return False


if homebrew_server_running():
    print('auto update: skipped (a Homebrew lll up runs on this machine, which switches it off)')
    sys.exit(0)

server = stub_server()
url = f'http://127.0.0.1:{server.server_port}'
with tempfile.TemporaryDirectory(prefix='lll-auto-update-') as directory:
    root = Path(directory).resolve()
    stub = root / 'stub'
    stub.mkdir()
    calls = root / 'brew-calls'
    (stub / 'brew').write_text(f'#!/bin/sh\necho "$@" >> {calls}\necho brew-ran\nsleep 2\necho brew-done\n')
    (stub / 'brew').chmod(0o755)
    cellar = root / 'Cellar' / 'lll' / '1.0.0' / 'bin' / 'lll'
    cellar.parent.mkdir(parents=True)
    shutil.copy2(binary, cellar)
    (root / 'brew-bin').mkdir()
    brew_lll = root / 'brew-bin' / 'lll'
    brew_lll.symlink_to(cellar)

    base = {k: v for k, v in os.environ.items()
            if not k.startswith(('LLL_', 'XDG_')) and k not in ('HOME', 'CI')}
    base.update(PATH=f'{stub}:{base["PATH"]}', LC_ALL='C', LLL_URL=url, LLL_TOKEN='auto-token', LLL_TEAM='AUTO')

    def env(name, **extra):
        return dict(base, HOME=str(root / name), **extra)

    def config_dir(name):
        path = root / name / '.config' / 'lll'
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run(exe, environment):
        started = time.monotonic()
        r = subprocess.run([str(exe), 'api', 'GET', '/api/collections/teams/records'],
                           env=environment, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout) == json.loads(STUB_BODY), r.stdout
        # `lll api` reports the status on stderr; the rest is ours.
        assert r.stderr.startswith('200 OK\n'), r.stderr
        r.stderr = r.stderr.removeprefix('200 OK\n')
        return r, time.monotonic() - started

    def brew_calls():
        return calls.read_text().splitlines() if calls.exists() else []

    # Homebrew, server newer: one line, brew started detached, lll not held.
    first, took = run(brew_lll, env('brew'))
    log = config_dir('brew') / 'auto-update.log'
    mine = subprocess.run([str(binary), '--version'], capture_output=True, text=True).stdout.split()[1]
    assert first.stderr == (f'lll: updating {mine} -> 99.0.0 in the background (log: {log}). '
                            'Disable: LLL_AUTO_UPDATE=0\n'), first.stderr
    # lll has exited and the upgrade has not: it was not waited for.
    assert 'brew-done' not in log.read_text(), f'lll waited for the upgrade ({took:.1f}s)'
    for _ in range(100):
        if 'brew-done' in (log.read_text() if log.exists() else ''):
            break
        time.sleep(0.1)
    assert brew_calls() == ['upgrade lll'], brew_calls()
    text = log.read_text()
    assert text.endswith('upgrade lll\nbrew-ran\nbrew-done\n') and '-> 99.0.0: brew upgrade lll' in text, text
    for _ in range(50):
        if not (config_dir('brew') / 'auto-update.lock').exists():
            break
        time.sleep(0.1)
    assert not (config_dir('brew') / 'auto-update.lock').exists(), 'the lock outlived the upgrade'

    # The same day, the same server: nothing.
    second, _ = run(brew_lll, env('brew'))
    assert second.stderr == '', second.stderr
    assert second.stdout == first.stdout
    assert brew_calls() == ['upgrade lll'], brew_calls()

    # Every no keeps today's warning and starts nothing.
    (config_dir('configured') / 'lll.toml').write_text('auto_update = false\n')
    (config_dir('served') / 'board-login-url').write_text('http://127.0.0.1:8100/?board_token=x\n')
    (config_dir('locked') / 'auto-update.lock').write_text('1 now\n')
    cases = [
        ('env-off', brew_lll, env('env-off', LLL_AUTO_UPDATE='0')),
        ('configured', brew_lll, env('configured')),
        ('ci', brew_lll, env('ci', CI='true')),
        ('served', brew_lll, env('served')),
        ('locked', brew_lll, env('locked')),
        ('checkout', binary, env('checkout')),
    ]
    for name, exe, environment in cases:
        r, _ = run(exe, environment)
        lines = r.stderr.splitlines()
        assert len(lines) == 1 and lines[0].endswith(WARNING_END), f'{name}: {r.stderr}'
        assert r.stdout == first.stdout, name
        assert not (config_dir(name) / 'auto-update.log').exists(), name
    time.sleep(0.5)
    assert brew_calls() == ['upgrade lll'], brew_calls()

server.shutdown()
print(f'auto update: ok (lll returned in {took:.1f}s; the upgrade takes 2s)')
