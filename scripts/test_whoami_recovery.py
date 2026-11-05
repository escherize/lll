#!/usr/bin/env python3
"""Recovery orders a broken URL before an expired saved token."""
import base64
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading

binary = str(Path(sys.argv[1]).resolve())


class Healthy(http.server.BaseHTTPRequestHandler):
    calls = 0

    def do_GET(self):
        if self.path != '/api/health':
            self.send_response(404)
            self.end_headers()
            return
        type(self).calls += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"code":200}')

    def log_message(self, *_):
        pass


with tempfile.TemporaryDirectory(prefix='lll-whoami-recovery-') as directory:
    root = Path(directory)
    config = root / 'config' / 'lll' / 'lll.toml'
    config.parent.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_'))}
    env.update(HOME=str(root / 'home'), LLL_CONFIG_HOME=str(root / 'config'))
    payload = base64.urlsafe_b64encode(json.dumps({'id': 'fixturemember01', 'exp': 1}).encode()).decode().rstrip('=')
    token = 'eyJhbGciOiJIUzI1NiJ9.' + payload + '.fixture-signature'

    def whoami(url, extra=None):
        config.write_text(f'url = "{url}"\ntoken = "{token}"\n')
        config.chmod(0o600)
        result = subprocess.run([binary, 'whoami'], cwd=root, env={**env, **(extra or {})},
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 6, (result.returncode, result.stderr)
        assert result.stdout == '' and token not in result.stderr
        return result.stderr

    # Reserve the address without listening: no unrelated server can answer it.
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        url = f'http://127.0.0.1:{reserved.getsockname()[1]}'
        message = whoami(url)
        assert message.index(url) < message.index('expired at'), message
        assert message.index('lll login --token -') < message.index('lll token create'), message

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Healthy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        message = whoami(url)
        assert 'expired at' in message and 'lll login --token -' in message
        message = whoami(url, {'LLL_TOKEN': token})
        assert 'LLL_TOKEN outranks the saved token' in message
        assert 'lll login --token -' not in message, 'login cannot replace an environment override'
        assert Healthy.calls == 2, 'healthy-server controls did not reach the API'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

print('whoami recovery: URL first, token-stdin hint, healthy-server control and token precedence passed')
