#!/usr/bin/env python3
"""LLL-607: a CLI older than its server says so, once a day, on stderr only.

A real `lll up` proves the server advertises its own version and that equal
versions are silent. A stub discovery server stands in for a newer, an older
and a pre-version server, so no test-only override is needed in the binary.
"""
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
MARK = 'this lll is'
STUB_BODY = b'{"items":[],"totalItems":0,"page":1,"perPage":200}'


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(LC_ALL='C', **extra)
    return env


def run(env, *args):
    return subprocess.run([binary, *args], env=env, capture_output=True, timeout=30)


mine = run(clean_env(HOME='/nonexistent'), '--version').stdout.decode().split()[1]


def stub(discovery):
    """A server whose /.well-known/lll answers `discovery`; /api/ is a PB-shaped list."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
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


def against(discovery, root, name):
    """Two runs of `lll api` (JSON on stdout) against a stub, sharing one config home."""
    server = stub(discovery)
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        env = clean_env(HOME=str(root / name), LLL_URL=url, LLL_TOKEN='skew-token', LLL_TEAM='SKEW')
        runs = [run(env, 'api', 'GET', '/api/collections/teams/records') for _ in range(2)]
        for r in runs:
            assert r.returncode == 0, r.stderr.decode()
        return url, runs
    finally:
        server.shutdown()


with tempfile.TemporaryDirectory(prefix='lll-version-skew-') as directory:
    root = Path(directory)

    # Newer server: one line on stderr, the first run of the day only.
    url, (first, second) = against({'service': 'lll', 'web_url': '.', 'version': '99.0.0'}, root, 'newer')
    warned = [line for line in first.stderr.decode().splitlines() if MARK in line]
    assert len(warned) == 1, first.stderr
    assert f'this lll is {mine}; {url} runs 99.0.0' in warned[0], warned
    assert 'Upgrade: ' in warned[0], warned
    assert MARK not in second.stderr.decode(), 'warned twice in one day: ' + second.stderr.decode()
    # stdout is byte-identical with and without the line, and still the raw JSON.
    assert first.stdout == second.stdout, (first.stdout, second.stdout)
    assert MARK.encode() not in first.stdout
    assert json.loads(first.stdout) == json.loads(STUB_BODY)

    # Same, older, and no-version servers say nothing.
    for name, discovery in [('same', {'service': 'lll', 'web_url': '.', 'version': mine}),
                            ('older', {'service': 'lll', 'web_url': '.', 'version': '0.0.1'}),
                            ('unversioned', {'service': 'lll', 'web_url': '.'})]:
        _, runs = against(discovery, root, name)
        for r in runs:
            assert MARK not in r.stderr.decode(), f'{name}: {r.stderr.decode()}'
            assert r.stdout == first.stdout, f'{name}: {r.stdout!r}'

    # A real server advertises its own version, and the same build is silent.
    home = root / 'real-home'
    home.mkdir()
    env = clean_env(HOME=str(home), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='SKEW', LLL_BIND='127.0.0.1',
                    USER='skew-owner', LLL_ADMIN_EMAIL='skew@example.invalid',
                    LLL_ADMIN_PASSWORD='local-version-skew-password', LLL_BOARD_TOKEN='local-version-skew-board')
    log = root / 'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        endpoints = wait_for_endpoints(log)
        board = endpoints['board_url']
        login = urllib.request.Request(endpoints['db_url'] + '/api/collections/_superusers/auth-with-password',
                                       headers={'Content-Type': 'application/json'},
                                       data=json.dumps({'identity': env['LLL_ADMIN_EMAIL'],
                                                        'password': env['LLL_ADMIN_PASSWORD']}).encode())
        with urllib.request.urlopen(login, timeout=10) as resp:
            token = json.load(resp)['token']
        with urllib.request.urlopen(board + '/.well-known/lll', timeout=10) as resp:
            advertised = json.load(resp)
        assert advertised == {'service': 'lll', 'web_url': '.', 'version': mine}, advertised
        out = subprocess.run([binary, 'team', 'list', '--json'], cwd=root, env=dict(env, LLL_URL=board, LLL_TOKEN=token),
                             capture_output=True, timeout=30)
        assert out.returncode == 0, out.stderr.decode()
        assert MARK not in out.stderr.decode(), out.stderr.decode()
        json.loads(out.stdout)
        stamps = list((home / '.config' / 'lll' / 'version-checks').iterdir())
        assert len(stamps) == 1, 'the real server was never probed'
    finally:
        child.terminate()
        child.wait(timeout=10)

print('version skew: ok')
