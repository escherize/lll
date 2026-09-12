#!/usr/bin/env python3
"""Exercise login discovery against the web suite's isolated API and board."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

binary, api, board = sys.argv[1:]
with tempfile.TemporaryDirectory() as directory:
    home = Path(directory)
    env = {key: value for key, value in os.environ.items() if not key.startswith('LLL_')}
    env['HOME'] = directory
    def login(url, *flags):
        result = subprocess.run([binary, 'login', '--url', url, '--email', 'e2e@members.invalid',
                                 '--password', 'web-e2e-pass-123', *flags],
                                cwd=directory, env=env, capture_output=True, text=True, timeout=12)
        assert result.returncode == 0, result.stderr
        return result.stdout
    def saved_board():
        for line in (home / '.config/lll/lll.toml').read_text().splitlines():
            if line.startswith('web_url = '):
                return json.loads(line.split('=', 1)[1].strip())
        return None

    assert 'board endpoint discovered' in login(board)
    assert saved_board() == board
    # Switching to a distinct API listener obtains the advertised board URL.
    assert 'board endpoint discovered' in login(api)
    assert saved_board() == board
    override = 'https://explicit.example.test/board'
    login(api, '--web-url', override)
    assert saved_board() == override
    login(api)
    assert saved_board() == override

    class DiscoveryProxy(http.server.BaseHTTPRequestHandler):
        advertisement = b'broken'
        status = 200
        def do_GET(self):
            if self.path == '/.well-known/lll':
                assert not self.headers.get('Authorization'), 'discovery sent credentials'
                self.send_response(self.status)
                if self.status == 302:
                    self.send_header('Location', board + '/.well-known/lll')
                self.end_headers()
                self.wfile.write(self.advertisement)
                return
            self.forward()
        def do_POST(self):
            self.forward()
        def forward(self):
            data = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if self.command == 'POST' else None
            headers = {name: self.headers[name] for name in ('Authorization', 'Content-Type') if name in self.headers}
            request = urllib.request.Request(api + self.path, data=data, headers=headers, method=self.command)
            try:
                response = urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                body = response.read()
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), DiscoveryProxy)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    target = f'http://127.0.0.1:{server.server_port}'
    try:
        for status, advertisement in [(200, b'broken'), (404, b'{}'), (302, b''),
                                      (200, b' ' * 4097),
                                      (200, b'{"service":"other","web_url":"."}')]:
            login(api, '--web-url', override)
            DiscoveryProxy.status, DiscoveryProxy.advertisement = status, advertisement
            output = login(target)
            assert saved_board() is None, (status, 'stale or unverified endpoint persisted')
            assert 'logged in as e2e' in output
            assert 'board endpoint: run' in output
        # An environment API override must not hide a saved server switch.
        login(api, '--web-url', override)
        env['LLL_URL'] = target
        login(target)
        assert saved_board() is None
        del env['LLL_URL']
        DiscoveryProxy.status = 200
        DiscoveryProxy.advertisement = json.dumps({'service': 'lll', 'web_url': board}).encode()
        assert 'board endpoint discovered' in login(target)
        assert saved_board() == board
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
print('login discovery: same-origin, split-origin, overrides, switching and optional fallback passed')
