#!/usr/bin/env python3
"""Exercise private machine config writes through login, config and logout."""
import http.server
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading

binary = str(Path(sys.argv[1]).resolve())


class Auth(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/collections/teams/records'):
            body = json.dumps({'items': [{'id': 'fixtureteam0001', 'key': 'TEST',
                                         'name': 'Fixture', 'archived': False}],
                               'totalItems': 1, 'totalPages': 1}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != '/api/collections/members/auth-with-password':
            self.send_error(404)
            return
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        body = json.dumps({'token': 'fake-config-permission-token',
                           'record': {'id': 'fixturemember01', 'name': 'fixture'}}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


with tempfile.TemporaryDirectory(prefix='lll-config-permissions-') as directory:
    root = Path(directory)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
    env.update(HOME=directory, LLL_CONFIG_HOME=str(root / 'config'),
               XDG_CONFIG_HOME=str(root / 'config'))
    config = root / 'config/lll/lll.toml'
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Auth)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    api = f'http://127.0.0.1:{server.server_port}'

    def run(*args):
        result = subprocess.run([binary, *args], cwd=root, env=env, text=True,
                                capture_output=True, timeout=10, umask=0o022)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def private():
        mode = stat.S_IMODE(config.stat().st_mode)
        assert mode == 0o600, f'machine config mode {mode:04o}, expected 0600'

    def login():
        run('login', '--url', api, '--email', 'fixture@example.invalid',
            '--password', 'fake-member-password', '--web-url', 'https://board.example.invalid')

    try:
        # First login creates a private file even under the usual 022 umask.
        login()
        private()
        assert 'fake-config-permission-token' in config.read_text()
        # Existing public config is tightened; replacing a token retains other keys.
        config.write_text('# keep this comment\nsort = "priority"\n'
                          'token = "old-fake-token"\n')
        config.chmod(0o644)
        login()
        private()
        text = config.read_text()
        assert '# keep this comment' in text and 'sort = "priority"' in text
        assert 'old-fake-token' not in text and 'fake-config-permission-token' in text
        # Endpoint writes also tighten legacy configs and preserve their credential.
        config.chmod(0o644)
        run('config', 'set', 'url', api)
        private()
        config.chmod(0o644)
        run('config', 'set', 'web_url', 'https://changed.example.invalid')
        private()
        assert 'fake-config-permission-token' in config.read_text()
        config.chmod(0o644)
        run('logout')
        private()
        text = config.read_text()
        assert 'token = ' not in text
        assert 'sort = "priority"' in text and '# keep this comment' in text
        assert 'web_url = "https://changed.example.invalid"' in text
        assert api in text
        # Machine endpoint setup without an existing file is private too.
        config.unlink()
        run('config', 'set', 'url', api)
        private()
        # The shareable repository template retains its public permissions.
        run('config', 'init')
        repo = root / '.lll.toml'
        assert stat.S_IMODE(repo.stat().st_mode) == 0o644
        assert 'fake-config-permission-token' not in repo.read_text()
        repo.unlink()
        run('attach', '-k', 'TEST')
        assert stat.S_IMODE(repo.stat().st_mode) == 0o644
        assert 'team = \"TEST\"' in repo.read_text()
        private()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
print('Config permissions: login/new and legacy files, endpoint changes and logout stay 0600; repo template stays 0644')
