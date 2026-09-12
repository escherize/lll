#!/usr/bin/env python3
"""Exercise startup error paths against an isolated API that refuses writes."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


class API(http.server.BaseHTTPRequestHandler):
    status = 403
    creates = 0

    def reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        # Whitespace is deliberate: auth diagnosis must parse list metadata.
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        if self.path == '/api/health':
            self.reply(200, {'code': 200})
        elif self.path.startswith('/api/collections/teams/records'):
            self.reply(200, {'items': [], 'totalItems': 0})
        else:
            self.reply(404, {'message': 'not found'})

    def do_POST(self):
        if self.path == '/api/collections/teams/records':
            type(self).creates += 1
            self.reply(self.status, {'message': 'fixture team creation refused'})
        else:
            self.reply(404, {'message': 'not found'})

    def log_message(self, *_):
        pass


binary = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory() as directory:
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), API)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_env = {k: v for k, v in os.environ.items() if not k.startswith('LLL_')}
        base_env.update(HOME=directory, LLL_URL=f'http://127.0.0.1:{server.server_port}')
        config = Path(directory) / '.config/lll/lll.toml'
        config.parent.mkdir(parents=True)
        for source in ('env', 'file'):
            env = dict(base_env)
            if source == 'env':
                env['LLL_TOKEN'] = 'fixture-opaque-token'
                origin = 'env:LLL_TOKEN'
            else:
                config.write_text('token = "fixture-opaque-token"\n')
                origin = f'file:{config}'
            for configured in (True, False):
                for status in (401, 403, 500):
                    API.status = status
                    API.creates = 0
                    scoped = dict(env)
                    if configured:
                        scoped['LLL_TEAM'] = 'DEMO'
                    result = subprocess.run([binary, 'up', '--no-open', '--pb-dir', directory + '/unused'],
                                            cwd=directory, env=scoped, input='DEMO\n',
                                            text=True, capture_output=True, timeout=10)
                    output = result.stdout + result.stderr
                    assert result.returncode != 0, output
                    assert API.creates == 1, output
                    assert str(status) in output and 'fixture team creation refused' in output, output
                    assert origin in output, output
                    assert 'none exists to reuse' not in output, output
                    assert 'fixture-opaque-token' not in output, output
        # A malformed JWT is diagnosed on the lookup, before any write.
        env = dict(base_env, LLL_TOKEN='bad.bad.bad', LLL_TEAM='DEMO')
        API.creates = 0
        result = subprocess.run([binary, 'up', '--no-open', '--pb-dir', directory + '/unused'],
                                cwd=directory, env=env, input='', text=True,
                                capture_output=True, timeout=10)
        output = result.stdout + result.stderr
        assert result.returncode != 0 and API.creates == 0, output
        assert 'LLL_TOKEN' in output and 'corrupt' in output, output
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
print('Startup errors: configured/prompted teams preserve 401/403/500 and credential origins')
