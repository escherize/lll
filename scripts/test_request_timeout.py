#!/usr/bin/env python3
"""LLL-623: no request to a server that stops answering hangs forever.

- A server that accepts the connection and never answers fails an ordinary
  command within the 30-second request budget, with the network exit code
  and a message saying what happened.
- An upload that takes longer than that budget to send still succeeds: a
  transfer's answer limit runs from the end of the request to the start of
  the answer.
- A transfer whose answer starts and then stops (a download, an upload's
  response) fails after 60 seconds without a byte.
- A realtime stream that sent its headers and a keepalive and then went
  silent is dropped and reconnected after 90 seconds without a line.

Every case waits out a real limit, so they all run side by side.
"""
import http.client
import http.server
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
ANSWER_SECONDS = 30
STALL_SECONDS = 60
STREAM_IDLE_SECONDS = 90
NETWORK_EXIT = 1
env = dict(os.environ, LLL_TEAM='ENG')


def cli(*args, url=api, timeout=30):
    return subprocess.run([binary, *args], env=dict(env, LLL_URL=url),
        capture_output=True, text=True, timeout=timeout)


def new_issue(title):
    created = cli('issue', 'create', title, '--json')
    assert created.returncode == 0, created.stderr
    return f"ENG-{json.loads(created.stdout)['number']}"


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


class Forward(http.server.BaseHTTPRequestHandler):
    """Forwards every request to the API; a subclass's intercept() may take
    a request over instead (returning True)."""
    protocol_version = 'HTTP/1.1'

    def intercept(self, data):
        return False

    def body(self):
        length = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(length) if length else None

    def read_body(self):
        return self.body()

    def forward(self):
        data = self.read_body()
        if self.intercept(data):
            return
        headers = {'Authorization': self.headers.get('Authorization', '')}
        if self.headers.get('Content-Type'):
            headers['Content-Type'] = self.headers['Content-Type']
        request = urllib.request.Request(api + self.path, method=self.command, data=data, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            answer = response.read()
            self.send_response(response.status)
            self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
            self.send_header('Content-Length', str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

    def stall(self, content_type='application/octet-stream'):
        """Start an answer, send a few bytes of it, then say nothing."""
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', '1000000')
        self.end_headers()
        self.wfile.write(b'{"partial":')
        self.wfile.flush()
        time.sleep(STALL_SECONDS * 3)
        self.close_connection = True

    do_GET = do_POST = do_PATCH = do_DELETE = forward

    def log_message(self, *args):
        pass


def serve(handler, server_class=http.server.ThreadingHTTPServer):
    server = server_class(('127.0.0.1', 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{server.server_port}'


# --- an ordinary request to a server that never answers ---

def silent_server_case(out):
    port = silent_listener()
    start = time.monotonic()
    result = cli('whoami', url=f'http://127.0.0.1:{port}', timeout=ANSWER_SECONDS * 3)
    out['silent'] = (result, time.monotonic() - start, port)


# --- an upload slower than the request budget ---

UPLOAD_BYTES = 16 * 1024 * 1024  # under the schema's 20 MiB per file
UPLOAD_SECONDS = ANSWER_SECONDS + 10
CHUNK = 64 * 1024


class SlowLink(http.server.ThreadingHTTPServer):
    """A small receive buffer, so the CLI's send really waits on the reads."""
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, CHUNK)
        super().server_bind()


class SlowUpload(Forward):
    """Reads a multipart upload's body at a pace that takes UPLOAD_SECONDS,
    like a slow link, then forwards it."""
    paced = []

    def read_body(self):
        length = int(self.headers.get('Content-Length') or 0)
        if not self.headers.get('Content-Type', '').startswith('multipart/'):
            return self.body()
        self.paced.append(self.path)
        pause = UPLOAD_SECONDS * CHUNK / length
        data = b''
        while len(data) < length:
            part = self.rfile.read(min(CHUNK, length - len(data)))
            assert part, 'the upload ended early'
            data += part
            time.sleep(pause)
        return data


def slow_upload_case(out):
    key = new_issue('Slow upload')
    url = serve(SlowUpload, SlowLink)
    with tempfile.TemporaryDirectory() as tmp:
        attachment = Path(tmp, 'slow.bin')
        attachment.write_bytes(os.urandom(UPLOAD_BYTES))
        start = time.monotonic()
        result = cli('issue', 'attach', key, str(attachment), url=url, timeout=ANSWER_SECONDS * 3)
        out['upload'] = (result, time.monotonic() - start, key)


# --- transfers whose answer starts and then stops ---

class StalledDownload(Forward):
    def intercept(self, data):
        if self.command == 'GET' and self.path.startswith('/api/files/issues/'):
            self.stall()
            return True
        return False


class StalledUploadAnswer(Forward):
    def intercept(self, data):
        if self.headers.get('Content-Type', '').startswith('multipart/'):
            self.stall('application/json')
            return True
        return False


def stalled_download_case(out):
    key = new_issue('Stalled download')
    with tempfile.TemporaryDirectory() as tmp:
        attachment = Path(tmp, 'stalled.txt')
        attachment.write_text('never fully read\n')
        attached = cli('issue', 'attach', key, str(attachment))
        assert attached.returncode == 0, attached.stderr
    name = re.search(r'^Attached to \S+: (\S+)$', attached.stdout, re.M).group(1)
    start = time.monotonic()
    result = cli('issue', 'download', key, name, url=serve(StalledDownload), timeout=STALL_SECONDS * 3)
    out['download'] = (result, time.monotonic() - start)


def stalled_upload_answer_case(out):
    key = new_issue('Stalled upload answer')
    with tempfile.TemporaryDirectory() as tmp:
        attachment = Path(tmp, 'answer.txt')
        attachment.write_text('the answer stalls\n')
        start = time.monotonic()
        result = cli('issue', 'attach', key, str(attachment), url=serve(StalledUploadAnswer),
            timeout=STALL_SECONDS * 3)
    out['upload_answer'] = (result, time.monotonic() - start)


# --- a realtime stream that goes silent after its first keepalive ---

class SilentStream(Forward):
    """Opens the real stream upstream (so the subscription the CLI posts is
    accepted), passes on its PB_CONNECT and one keepalive, then sends
    nothing more."""
    protocol_version = 'HTTP/1.0'  # the answer ends when the connection does

    def intercept(self, data):
        if self.command != 'GET' or urllib.parse.urlsplit(self.path).path != '/api/realtime':
            return False
        target = urllib.parse.urlsplit(api)
        upstream = http.client.HTTPConnection(target.hostname, target.port, timeout=STALL_SECONDS * 3)
        upstream.request('GET', '/api/realtime', headers={'Authorization': self.headers.get('Authorization', '')})
        stream = upstream.getresponse()
        frame = []
        while True:
            line = stream.readline()
            frame.append(line)
            if line in (b'\n', b'\r\n', b''):
                break
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        self.wfile.write(b''.join(frame) + b': keepalive\n\n')
        self.wfile.flush()
        time.sleep(STREAM_IDLE_SECONDS * 2)
        upstream.close()
        return True


def silent_stream_case(out):
    watch = subprocess.Popen([binary, 'watch', '--team', 'ENG'], env=dict(env, LLL_URL=serve(SilentStream)),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    lines = []

    def read():
        for line in watch.stderr:
            lines.append((time.monotonic(), line.strip()))

    threading.Thread(target=read, daemon=True).start()
    ready = lost = None
    deadline = time.monotonic() + STREAM_IDLE_SECONDS * 2
    while time.monotonic() < deadline and lost is None:
        for at, line in list(lines):
            if ready is None and line.startswith('watch: ready'):
                ready = at
            if lost is None and line == 'realtime: lll server stream lost; reconnecting':
                lost = at
        time.sleep(0.5)
    watch.terminate()
    watch.wait(timeout=10)
    out['stream'] = (ready, lost, [line for _, line in lines])


out = {}
cases = [threading.Thread(target=case, args=(out,)) for case in (
    silent_server_case, slow_upload_case, stalled_download_case, stalled_upload_answer_case, silent_stream_case)]
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

result, upload_elapsed, key = out['upload']
assert result.returncode == 0, result.stderr
assert f'Attached to {key}: slow' in result.stdout, result.stdout
assert SlowUpload.paced, 'the upload never reached the slow link'
assert upload_elapsed > ANSWER_SECONDS, upload_elapsed

for case in ('download', 'upload_answer'):
    result, elapsed = out[case]
    assert result.returncode == NETWORK_EXIT, (case, result.returncode, result.stderr)
    assert f'stopped sending for {STALL_SECONDS}s partway through its answer' in result.stderr, (case, result.stderr)
    assert 'token=' not in result.stderr, (case, 'a file token leaked', result.stderr)
    assert STALL_SECONDS - 1 <= elapsed < STALL_SECONDS + 20, (case, elapsed)

ready, lost, lines = out['stream']
assert ready is not None, lines
assert lost is not None, f'a silent stream was never dropped: {lines}'
assert STREAM_IDLE_SECONDS - 5 <= lost - ready < STREAM_IDLE_SECONDS + 20, (lost - ready, lines)

print(f'request timeout: silent server failed in {out["silent"][1]:.0f}s; slow upload succeeded in '
      f'{upload_elapsed:.0f}s; stalled download and upload answer failed in {out["download"][1]:.0f}s and '
      f'{out["upload_answer"][1]:.0f}s; silent stream dropped after {lost - ready:.0f}s')
