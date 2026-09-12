#!/usr/bin/env python3
"""Deterministic watch condition checks using the CLI suite's isolated server."""
import http.server
import json
import os
import selectors
import subprocess
import sys
import threading
import urllib.request

binary, api, key = sys.argv[1:]
env = dict(os.environ, LLL_URL=api)
def cli(*args):
    return subprocess.check_output([binary, *args], env=env, text=True, timeout=12)
issue = json.loads(cli('issue', 'view', key, '--json'))
def create(body):
    request = urllib.request.Request(api + '/api/collections/comments/records',
        data=json.dumps({'issue': issue['id'], 'body': body}).encode(),
        headers={'Authorization': 'Bearer ' + env['LLL_TOKEN'], 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)
def watch(text):
    return [binary, 'issue', 'watch', key, '--until', text, '--timeout', '4', '--json']
existing = json.loads(subprocess.check_output(watch('Watching closely'), env=env, text=True, timeout=8))
assert existing['action'] == 'snapshot' and existing['topic'] == 'comments'

def arriving(text, mutate):
    process = subprocess.Popen(watch(text), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stderr, selectors.EVENT_READ)
            assert selector.select(5), 'watch never acknowledged readiness'
            assert 'watch: ready' in process.stderr.readline()
        mutate()
        out, err = process.communicate(timeout=8)
        assert process.returncode == 0, err
        events = [json.loads(line) for line in out.splitlines()]
        assert any(text in event['record'].get('body', '') for event in events), events
        return events
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
assert arriving('json-arriving-match', lambda: create('json-arriving-match'))[-1]['action'] == 'create'
record = create('not ready for edit')
def edit():
    request = urllib.request.Request(api + '/api/collections/comments/records/' + record['id'], method='PATCH',
        data=b'{"body":"json-edited-match"}',
        headers={'Authorization': 'Bearer ' + env['LLL_TOKEN'], 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200
assert arriving('json-edited-match', edit)[-1]['action'] == 'update'
for value in ['0', '-1', 'nope', '9223372037']:
    result = subprocess.run([binary, 'issue', 'watch', key, '--until', 'x', '--timeout', value],
                            env=dict(env, LLL_URL='http://127.0.0.1:1'), capture_output=True, text=True, timeout=3)
    assert result.returncode != 0 and '--timeout' in result.stderr, result

# Emulate the setup gap: persist a comment just before accepting the
# subscription, with no event emitted for that pre-subscription write.
stopped = threading.Event()
class SetupRace(http.server.BaseHTTPRequestHandler):
    stall = False
    def do_GET(self):
        if self.path == '/api/realtime':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            if self.stall:
                self.wfile.flush()
                stopped.wait(10)
                return
            self.wfile.write(b'event: PB_CONNECT\ndata: {"clientId":"setup-race"}\n\n')
            self.wfile.flush()
            stopped.wait(10)
            return
        request = urllib.request.Request(api + self.path, headers={'Authorization': self.headers.get('Authorization', '')})
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        assert self.path == '/api/realtime'
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        create('setup-race-match')
        self.send_response(204)
        self.end_headers()
    def log_message(self, *args):
        pass
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), SetupRace)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    result = subprocess.run(watch('setup-race-match'),
        env=dict(env, LLL_URL=f'http://127.0.0.1:{server.server_port}'),
        capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stderr
    event = json.loads(result.stdout)
    assert event['action'] == 'snapshot' and event['record']['body'] == 'setup-race-match', event
    SetupRace.stall = True
    stalled = subprocess.run([binary, 'issue', 'watch', key, '--until', 'never', '--timeout', '1'],
        env=dict(env, LLL_URL=f'http://127.0.0.1:{server.server_port}'),
        capture_output=True, text=True, timeout=4)
    assert stalled.returncode != 0 and 'within 1s' in stalled.stderr, stalled
finally:
    stopped.set()
    server.shutdown()
    server.server_close()
    thread.join()
print('watch --until: existing/create/update JSON matches, invalid deadlines and subscription race passed')
