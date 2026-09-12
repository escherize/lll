#!/usr/bin/env python3
"""Complete boards, later-page ordering, and real upstream failure recovery."""
from concurrent.futures import ThreadPoolExecutor
import base64
import http.server
import json
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import subprocess
from browser_session import new_session, open_session
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

binary, api, board = sys.argv[1:]
cookie = 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN']
token = os.environ['LLL_TOKEN']


def api_request(path, body=None, method=None):
    req = urllib.request.Request(api + path, data=None if body is None else json.dumps(body).encode(),
        method=method, headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def web_request(base, path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else urllib.parse.urlencode(body).encode(),
        headers={'Cookie': cookie, 'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        response = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, response.read().decode()


def cards(text):
    return re.findall(r'class="card" id="issue-([^\"]+)"', text)


team = api_request('/api/collections/teams/records', {'key': 'BP360', 'name': 'Complete boards'})
def seed(n):
    return api_request('/api/collections/issues/records', {'team': team['id'], 'title': 'Board page ' + str(n),
        'state': 'todo', 'sort': n + 1000})
with ThreadPoolExecutor(max_workers=8) as pool:
    rows = list(pool.map(seed, range(204)))
rows.append(seed(204))
expected = [row['id'] for row in rows]
status, initial = web_request(board, '/t/BP360/')
assert status == 200 and cards(initial) == expected
assert len(set(cards(initial))) == 205
# A drop before a later-page target must use its real predecessor.
status, body = web_request(board, '/state', {'key': 'BP360-' + str(rows[0]['number']), 'state': 'todo', 'before': rows[-1]['id']})
assert status == 200 and '503' not in body
updated = api_request('/api/collections/issues/records/' + rows[0]['id'])
assert rows[-2]['sort'] < updated['sort'] < rows[-1]['sort']
expected = expected[1:-1] + [expected[0], expected[-1]]
assert cards(web_request(board, '/t/BP360/')[1]) == expected


class Proxy(http.server.BaseHTTPRequestHandler):
    fail = threading.Event()

    def log_message(self, *_):
        pass

    def forward(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if self.fail.is_set() and parsed.path == '/api/collections/issues/records' and query.get('page') == ['2']:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"message":"board second page unavailable"}')
            return
        data = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if self.command in ['POST', 'PATCH'] else None
        req = urllib.request.Request(api + self.path, data=data, method=self.command,
            headers={'Authorization': self.headers.get('Authorization', ''), 'Content-Type': self.headers.get('Content-Type', 'application/json')})
        try:
            response = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.send_response(response.code)
            self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
            self.end_headers()
            try:
                if 'text/event-stream' in response.headers.get('Content-Type', ''):
                    for line in response:
                        self.wfile.write(line)
                        self.wfile.flush()
                else:
                    self.wfile.write(response.read())
            except (BrokenPipeError, ConnectionResetError):
                pass

    do_GET = forward
    do_POST = forward
    do_PATCH = forward
    do_DELETE = forward


class Stream:
    def __init__(self, base):
        self.response = urllib.request.urlopen(urllib.request.Request(base + '/events?page=board&team=BP360',
            headers={'Cookie': cookie}), timeout=30)
        self.events = queue.Queue()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        event = ''
        try:
            for line in self.response:
                event += line.decode()
                if line == b'\n':
                    self.events.put(event)
                    event = ''
        except Exception as error:
            self.events.put(error)

    def until(self, predicate):
        observed = []
        for _ in range(100):
            event = self.events.get(timeout=25)
            assert isinstance(event, str), str(event)
            observed.append(event)
            if predicate(event):
                return observed
        raise AssertionError('missing board stream barrier')


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
threading.Thread(target=server.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory(prefix='lll-board-pages-') as directory:
    # Adopt only the owned loopback fixture through its proxy. This second
    # board has its own HOME/cwd and process; it never starts another database.
    subject = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))['id']
    members = api_request('/api/collections/members/records?perPage=200')['items']
    actor = next((m for m in members if m['id'] == subject), members[0])
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith('LLL_')}
    env.update(HOME=directory, LLL_URL='http://127.0.0.1:' + str(server.server_port), LLL_TOKEN=token,
        LLL_TEAM='BP360', LLL_ME=actor['name'], LLL_BIND='127.0.0.1', LLL_BOARD_TOKEN=os.environ['LLL_TEST_BOARD_TOKEN'])
    log = Path(directory) / 'board.log'
    with log.open('w') as output:
        process = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port)], cwd=directory,
            env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 25
        proxy_board = None
        while time.monotonic() < deadline:
            assert process.poll() is None, 'isolated board exited before listening'
            match = re.search(r'^board  (http://127.0.0.1:\d+)$', log.read_text(), re.M)
            if match:
                proxy_board = match.group(1)
                break
            time.sleep(0.05)
        assert proxy_board, 'isolated board never announced its bound listener'
        victim = rows[-1]
        victim_path = '/api/collections/issues/records/' + victim['id']
        api_request('/api/collections/favorites/records', {'issue': victim['id']})
        stream = Stream(proxy_board)
        stream.until(lambda e: cards(e) == expected)
        Proxy.fail.set()
        api_request(victim_path, {'title': 'Second page failure barrier'}, 'PATCH')
        observed = stream.until(lambda e: 'id="rail-favorites"' in e and 'Second page failure barrier' in e)
        assert all(not cards(e) or cards(e) == expected for e in observed), 'failed refresh published a partial board'
        status, body = web_request(proxy_board, '/t/BP360/')
        assert status == 500 and '503' in body and not cards(body)
        before = api_request(victim_path)
        status, body = web_request(proxy_board, '/state', {'key': 'BP360-205', 'state': 'done'})
        assert status == 200 and '503' in body
        assert 'class="error-summary"' in body and '<details class="error-details">' in body
        assert '<details class="error-details" open' not in body
        assert api_request(victim_path) == before, 'failed reorder changed the issue'
        Proxy.fail.clear()
        api_request(victim_path, {'title': 'Recovered full board'}, 'PATCH')
        observed = stream.until(lambda e: 'Recovered full board' in e and bool(cards(e)))
        assert cards(observed[-1]) == expected
        assert cards(web_request(proxy_board, '/t/BP360/')[1]) == expected
    finally:
        process.terminate()
        process.wait(timeout=15)
        server.shutdown()
        server.server_close()

if shutil.which('playwright-cli'):
    session = new_session()
    try:
        open_session(session, board + '/?board_token=' + os.environ['LLL_TEST_BOARD_TOKEN'])
        result = subprocess.run(['playwright-cli', '-s=' + session, 'run-code', Path('scripts/browser_board_pagination.js').read_text()], capture_output=True, text=True, timeout=90)
        output = result.stdout + result.stderr
        Path('/tmp/lll-360-browser.log').write_text(output)
        assert result.returncode == 0 and '### Error' not in output and '### Result\n"Complete board browser passed"' in output, 'see /tmp/lll-360-browser.log'
    finally:
        subprocess.run(['playwright-cli', '-s=' + session, 'close'], capture_output=True, timeout=15)
print('Board pagination: 205 cards, stable order, later-page drop target, HTTP/SSE failure preservation, recovery and live browser update passed')
