#!/usr/bin/env python3
"""A relocated board must not let fixtures probe an unrelated listener."""
import http.server
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error

from board_startup import wait_for_board


class Stranger(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'unrelated listener')
    def log_message(self, *args):
        pass

binary = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='lll-243-') as directory:
    base = Path(directory)
    (base / 'home').mkdir()
    stranger = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Stranger)
    threading.Thread(target=stranger.serve_forever, daemon=True).start()
    web = stranger.server_port
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        db = reservation.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith('LLL_')}
    env.update(HOME=str(base / 'home'), USER='collision', LLL_TEAM='COLLIDE',
               LLL_URL=f'http://127.0.0.1:{db}', LLL_BOARD_TOKEN='collision-fixture')
    log_path = base / 'up.log'
    with log_path.open('w') as log:
        process = subprocess.Popen([binary, 'up', '--no-open', '--port', str(web),
                                    '--pb-dir', str(base / 'data')], cwd=base, env=env,
                                   stdout=log, stderr=log, start_new_session=True)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                output = log_path.read_text()
                match = re.search(r'^board  http://127.0.0.1:(\d+)$', output, re.M)
                if match:
                    break
                assert process.poll() is None, 'owned server exited before banner'
                time.sleep(.1)
            else:
                raise AssertionError('owned board startup timed out')
            actual = int(match[1])
            assert actual != web
            try:
                wait_for_board(log_path, f'http://127.0.0.1:{web}')
                raise AssertionError('startup check accepted an unrelated endpoint')
            except AssertionError as error:
                assert 'refusing fixture requests to another listener' in str(error)
            wait_for_board(log_path, f'http://127.0.0.1:{actual}')
            with urllib.request.urlopen(f'http://127.0.0.1:{web}/', timeout=3) as response:
                assert response.status == 200
                assert response.read() == b'unrelated listener'
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{actual}/', timeout=3)
                raise AssertionError('owned board admitted anonymous request')
            except urllib.error.HTTPError as error:
                assert error.code == 401
            print('Board startup: occupied endpoint rejected; announced board accepts verification and refuses anonymous access')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            stranger.shutdown()
            stranger.server_close()
