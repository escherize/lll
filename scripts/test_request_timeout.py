#!/usr/bin/env python3
"""LLL-623: a server that accepts the connection and never answers fails a
command within the request timeout, with the network exit code and a message
saying what happened; an upload that takes longer than that timeout to send
still succeeds, because a transfer's limit runs only from the end of the
request to the start of the answer.

Both cases wait out the real 30-second budget, so they run side by side.
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
import time
import urllib.error
import urllib.request

binary, api = sys.argv[1:]
ANSWER_SECONDS = 30
NETWORK_EXIT = 1
env = dict(os.environ, LLL_TEAM='ENG')


def silent_listener():
    """Accepts connections and never reads or writes."""
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(16)
    held = []

    def accept():
        while True:
            conn, _ = sock.accept()
            held.append(conn)

    threading.Thread(target=accept, daemon=True).start()
    return sock.getsockname()[1]


def silent_server_case(out):
    port = silent_listener()
    start = time.monotonic()
    result = subprocess.run([binary, 'whoami'], env=dict(env, LLL_URL=f'http://127.0.0.1:{port}'),
        capture_output=True, text=True, timeout=ANSWER_SECONDS * 3)
    out['silent'] = (result, time.monotonic() - start, port)


UPLOAD_BYTES = 16 * 1024 * 1024  # under the schema's 20 MiB per file
UPLOAD_SECONDS = ANSWER_SECONDS + 10
CHUNK = 64 * 1024


class SlowLink(http.server.ThreadingHTTPServer):
    """A small receive buffer, so the CLI's send really waits on the reads."""
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, CHUNK)
        super().server_bind()


class SlowUpload(http.server.BaseHTTPRequestHandler):
    """Forwards to the API, reading a multipart upload's body at a pace that
    takes UPLOAD_SECONDS, like a slow link."""
    protocol_version = 'HTTP/1.1'
    paced = []

    def forward(self):
        length = int(self.headers.get('Content-Length') or 0)
        content_type = self.headers.get('Content-Type', '')
        if content_type.startswith('multipart/'):
            self.paced.append(self.path)
            pause = UPLOAD_SECONDS * CHUNK / length
            data = b''
            while len(data) < length:
                part = self.rfile.read(min(CHUNK, length - len(data)))
                assert part, 'the upload ended early'
                data += part
                time.sleep(pause)
        else:
            data = self.rfile.read(length) if length else None
        headers = {'Authorization': self.headers.get('Authorization', '')}
        if content_type:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(api + self.path, method=self.command, data=data, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            self.send_response(response.status)
            self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    do_GET = do_POST = do_PATCH = do_DELETE = forward

    def log_message(self, *args):
        pass


def slow_upload_case(out):
    created = subprocess.run([binary, 'issue', 'create', 'Slow upload', '--json'],
        env=dict(env, LLL_URL=api), capture_output=True, text=True, timeout=30)
    assert created.returncode == 0, created.stderr
    key = f"ENG-{json.loads(created.stdout)['number']}"
    server = SlowLink(('127.0.0.1', 0), SlowUpload)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory() as tmp:
        attachment = Path(tmp, 'slow.bin')
        attachment.write_bytes(os.urandom(UPLOAD_BYTES))
        start = time.monotonic()
        result = subprocess.run([binary, 'issue', 'attach', key, str(attachment)],
            env=dict(env, LLL_URL=f'http://127.0.0.1:{server.server_port}'),
            capture_output=True, text=True, timeout=ANSWER_SECONDS * 3)
        out['upload'] = (result, time.monotonic() - start, key)
    server.shutdown()


out = {}
cases = [threading.Thread(target=case, args=(out,)) for case in (silent_server_case, slow_upload_case)]
for case in cases:
    case.start()
for case in cases:
    case.join()

result, elapsed, port = out['silent']
assert result.returncode == NETWORK_EXIT, (result.returncode, result.stderr)
expected = f'the lll server at http://127.0.0.1:{port} accepted the connection but did not answer within {ANSWER_SECONDS}s'
assert expected in result.stderr, result.stderr
assert 'is the lll server running' not in result.stderr, result.stderr
assert ANSWER_SECONDS - 1 <= elapsed < ANSWER_SECONDS + 15, elapsed

result, elapsed, key = out['upload']
assert result.returncode == 0, result.stderr
assert f'Attached to {key}: slow' in result.stdout, result.stdout
assert SlowUpload.paced, 'the upload never reached the slow link'
assert elapsed > ANSWER_SECONDS, elapsed
print(f'request timeout: silent server failed in {out["silent"][1]:.0f}s; slow upload succeeded in {elapsed:.0f}s')
