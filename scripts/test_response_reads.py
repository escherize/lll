#!/usr/bin/env python3
"""HTTP framing errors fail even when the delivered prefix is valid JSON."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

binary = str(Path(sys.argv[1]).resolve())


class API(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    mode = 'complete'
    calls = []

    def reply(self):
        type(self).calls.append((self.command, self.path))
        if self.mode == 'http-error':
            body = b'{"message":"fixture request refused"}'
            status = 500
        else:
            body = json.dumps({'items': [{'id': 'fixture00000001', 'name': 'Fixture'}],
                               'totalPages': 1, 'totalItems': 1}).encode()
            status = 200
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        if self.mode == 'chunked':
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            # A complete JSON chunk, but no terminating zero chunk.
            self.wfile.write(f'{len(body):x}\r\n'.encode() + body + b'\r\n')
        else:
            length = len(body) + (25 if self.mode == 'short' else 0)
            self.send_header('Content-Length', str(length))
            self.end_headers()
            self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        self.reply()

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.reply()

    def log_message(self, *_):
        pass


with tempfile.TemporaryDirectory(prefix='lll-response-reads-') as directory:
    root = Path(directory)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), API)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
    env.update(HOME=directory, LLL_CONFIG_HOME=str(root / 'config'),
               LLL_URL=f'http://127.0.0.1:{server.server_port}',
               LLL_TOKEN='fake-response-read-token')

    def run(*args):
        return subprocess.run([binary, *args], cwd=root, env=env,
                              text=True, capture_output=True, timeout=15)

    try:
        result = run('member', 'list', '--json')
        assert result.returncode == 0 and len(json.loads(result.stdout)['items']) == 1, result
        for mode in ('short', 'chunked'):
            API.mode = mode
            for command in [('member', 'list', '--json'),
                            ('api', 'GET', '/api/collections/members/records'),
                            ('api', 'POST', '/api/collections/members/records', '--body', '{"name":"Fixture"}')]:
                API.calls = []
                result = run(*command)
                assert result.returncode != 0 and not result.stdout, (mode, command, result)
                assert 'reading response: unexpected EOF' in result.stderr, result.stderr
                assert len(API.calls) == 1, ('uncertain request retried', API.calls)
        API.mode = 'http-error'
        result = run('member', 'list', '--json')
        assert result.returncode != 0 and not result.stdout, result
        assert '500' in result.stderr and 'fixture request refused' in result.stderr, result.stderr
        raw = run('api', 'GET', '/api/collections/members/records')
        assert raw.returncode == 0 and '500' in raw.stderr, raw
        assert json.loads(raw.stdout)['message'] == 'fixture request refused', raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
print('Response reads: complete JSON succeeds; short/chunked EOF fails for list/GET/POST with no partial stdout or uncertain retry; HTTP errors preserved')
