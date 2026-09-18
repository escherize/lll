#!/usr/bin/env python3
"""Owned runtime and controlled proxy verify saved-view refresh ownership."""
import http.server
import json
import os
import queue
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys
binary = str(Path(sys.argv[1]).resolve())

class Proxy(http.server.BaseHTTPRequestHandler):
    fail = threading.Event()
    refused = threading.Event()

    def log_message(self, *_):
        pass

    def forward(self):
        parsed = urllib.parse.urlsplit(self.path)
        if self.fail.is_set() and parsed.path == '/api/collections/views/records':
            self.refused.set()
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"message":"saved views unavailable"}')
            return
        data = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if self.command in ['POST', 'PATCH'] else None
        req = urllib.request.Request(api + self.path, data=data, method=self.command, headers={'Authorization': self.headers.get('Authorization', ''), 'Content-Type': self.headers.get('Content-Type', 'application/json')})
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
        self.response = urllib.request.urlopen(urllib.request.Request(base + '/events?page=board&team=RVW', headers={'Cookie': cookie}), timeout=30)
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

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def request(path, body=None, token='', method=None):
    req = urllib.request.Request(api + path, data=None if body is None else json.dumps(body).encode(), method=method, headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + token} if token else {})})
    with urllib.request.urlopen(req, timeout=15) as response:
        return None if response.status == 204 else json.load(response)

def stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=5)

def wait_banner(p, log):
    until = time.monotonic() + 30
    while time.monotonic() < until:
        assert p.poll() is None, log.read_text()
        m = re.search('^board  (http://127.0.0.1:\\d+)$', log.read_text(), re.M)
        if m:
            return m.group(1)
        time.sleep(0.1)
    raise AssertionError(log.read_text())
with tempfile.TemporaryDirectory(prefix='lll-views-refresh-') as directory:
    root = Path(directory)
    primary = secondary = None
    server = None
    stream = None
    env = {k: v for k, v in os.environ.items() if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
    api = 'http://127.0.0.1:' + str(free_port())
    env.update(HOME=directory, LLL_CONFIG_HOME=directory + '/config', LLL_URL=api, LLL_TEAM='RVW', LLL_BIND='127.0.0.1', USER='reviewmember', LLL_ADMIN_EMAIL='review-admin@example.invalid', LLL_ADMIN_PASSWORD='throwaway-view-failure-password', LLL_BOARD_TOKEN='throwaway-view-failure-board')
    cookie = 'lll_board=throwaway-view-failure-board'
    try:
        log = root / 'primary.log'
        with log.open('w') as output:
            primary = subprocess.Popen([binary, 'up', '--no-open', '--port', str(free_port()), '--pb-dir', str(root / 'data')], cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
        wait_banner(primary, log)
        admin = request('/api/collections/_superusers/auth-with-password', {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})['token']
        members = request('/api/collections/members/records', token=admin)['items']
        member = next((m for m in members if m['name'] == 'reviewmember'))
        token = request('/api/collections/members/impersonate/' + member['id'], {'duration': 3600}, admin)['token']
        kept = request('/api/collections/views/records', {'name': 'Kept saved view', 'query': 'state=todo'}, token)
        team = next((t for t in request('/api/collections/teams/records', token=token)['items'] if t['key'] == 'RVW'))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        home = root / 'secondary'
        home.mkdir()
        childenv = {k: v for k, v in env.items() if not k.startswith('LLL_')}
        childenv.update(HOME=str(home), LLL_CONFIG_HOME=str(home / 'config'), LLL_URL='http://127.0.0.1:' + str(server.server_port), LLL_TOKEN=token, LLL_TEAM='RVW', LLL_BIND='127.0.0.1', LLL_BOARD_TOKEN='throwaway-view-failure-board')
        log = home / 'secondary.log'
        with log.open('w') as output:
            secondary = subprocess.Popen([binary, 'up', '--no-open', '--port', str(free_port())], cwd=home, env=childenv, stdout=output, stderr=subprocess.STDOUT)
        board = wait_banner(secondary, log)
        with urllib.request.urlopen(urllib.request.Request(board + '/t/RVW/', headers={'Cookie': cookie}), timeout=15) as response:
            assert b'Kept saved view' in response.read()
        stream = Stream(board)
        stream.until(lambda e: 'id="board"' in e)
        Proxy.fail.set()
        trigger = request('/api/collections/views/records', {'name': 'Trigger failed refresh', 'query': 'state=done'}, token)
        assert Proxy.refused.wait(15), 'refresh never attempted its read'
        request('/api/collections/issues/records', {'team': team['id'], 'title': 'Failed refresh barrier', 'state': 'todo'}, token)
        observed = stream.until(lambda e: 'id="board"' in e and 'Failed refresh barrier' in e)
        assert not any(('id="rail-views"' in e for e in observed)), 'failed read replaced visible saved views'
        with urllib.request.urlopen(urllib.request.Request(board + '/t/RVW/', headers={'Cookie': cookie}), timeout=15) as response:
            page = response.read().decode()
            assert response.status == 200 and 'id="rail-views"' in page and ('Kept saved view' not in page), 'initial-page fallback changed'
        Proxy.fail.clear()
        request('/api/collections/views/records/' + trigger['id'], {'name': 'Recovered saved view'}, token, 'PATCH')
        event = stream.until(lambda e: 'id="rail-views"' in e and 'Recovered saved view' in e)[-1]
        assert 'Kept saved view' in event, event
        created = request('/api/collections/views/records', {'name': 'Created after recovery', 'query': 'state=todo'}, token)
        stream.until(lambda e: 'id="rail-views"' in e and 'Created after recovery' in e)
        for view in (kept, trigger, created):
            request('/api/collections/views/records/' + view['id'], token=token, method='DELETE')
        empty = stream.until(lambda e: 'id="rail-views"' in e and 'class="rg-empty"' in e)[-1]
        assert all((name not in empty for name in ('Kept saved view', 'Recovered saved view', 'Created after recovery'))), empty
        print('Saved views: failed realtime read preserves prior group; page fallback, recovery/update/create and actual empty deletion pass')
    finally:
        stop(secondary)
        stop(primary)
        if stream:
            stream.response.close()
        if server:
            server.shutdown()
            server.server_close()
