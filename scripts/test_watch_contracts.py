#!/usr/bin/env python3
"""LLL-615: pin the answers that 'lll watch --help', 'lll bot rotate --help'
and docs/claim-transactions.md give to questions scripts used to guess.

1. Which claim operations reach 'lll watch' (only those that write the issue).
2. What text mode prints for a label-only update ('KEY changed').
3. Who may rotate a bot's token, and which tokens a rotation strands.
4. The exact status lines 'lll watch' prints, and that they go to stderr.
5. LLL-617: a watch whose token is rotated out exits 1 at the next reconnect,
   naming the fix, instead of reconnecting into a stream that carries nothing.

Run by e2e.sh with the built binary, the server URL, the suite's member token
in LLL_TOKEN and a fresh superuser token in LLL_TEST_SUPERUSER_TOKEN.
"""
import http.server
import json
import os
import selectors
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
token = os.environ['LLL_TOKEN']
superuser = os.environ['LLL_TEST_SUPERUSER_TOKEN']
# Member paths must not see the suite's admin pair: 'lll bot' treats it as
# the superuser speaking.
base = {k: v for k, v in os.environ.items() if not k.startswith('LLL_ADMIN_')}
env = dict(base, LLL_URL=api, LLL_TEAM='WCTR')


def request(path, body=None, method=None, auth=token):
    req = urllib.request.Request(api + path,
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={'Authorization': 'Bearer ' + auth, 'Content-Type': 'application/json'})
    try:
        response = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, json.load(response)


def post(collection, body):
    status, result = request('/api/collections/' + collection + '/records', body)
    assert status == 200, result
    return result


def cli(*args, as_token=token):
    return subprocess.run([binary, *args], env=dict(env, LLL_TOKEN=as_token),
                          capture_output=True, text=True, timeout=30)


def ok(*args, as_token=token):
    result = cli(*args, as_token=as_token)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result.stdout


def wait_ready(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stderr, selectors.EVENT_READ)
        assert selector.select(10), 'watch never acknowledged readiness'
    line = process.stderr.readline()
    assert line == 'watch: ready (query subscription accepted)\n', line


def wait_for(path, text, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with open(path) as f:
            content = f.read()
        if text in content:
            return content
        time.sleep(0.1)
    raise AssertionError(f'{text!r} never appeared in:\n{content}')


def member_token(name):
    password = 'watch-contract-123'
    member = post('members', {'name': name, 'email': name + '@lll.test',
        'password': password, 'passwordConfirm': password})
    status, auth = request('/api/collections/members/auth-with-password',
        {'identity': name + '@lll.test', 'password': password}, auth='')
    assert status == 200, auth
    return member, auth['token']


me = request('/api/collections/members/auth-refresh', {}, method='POST')[1]['record']
post('teams', {'key': 'WCTR', 'name': 'Watch contracts'})
ok('project', 'create', 'Fleet')
ok('label', 'create', 'bug')


def create(title, *extra):
    out = ok('issue', 'create', '-t', title, '--project', 'Fleet', *extra)
    return out.split()[1].rstrip(':')


held = create('Already mine', '--assignee', me['name'])
free = create('Nobody has it')
tagged = create('Gets a label')

# --- 1 and 2: claims and a label-only update, as the project watch sees them.
tmp = tempfile.mkdtemp(prefix='watch-contracts-')
text_out, json_out = os.path.join(tmp, 'text.out'), os.path.join(tmp, 'json.out')
watchers = []
for out_path, extra in [(text_out, []), (json_out, ['--json'])]:
    process = subprocess.Popen([binary, 'watch', '--project', 'Fleet', *extra], env=env,
                               stdout=open(out_path, 'w'), stderr=subprocess.PIPE, text=True)
    watchers.append(process)
try:
    for process in watchers:
        wait_ready(process)
    # No issue write, no event: claiming an issue already assigned to you,
    # renewing, and claiming it again. The title write after them is a
    # sentinel - once it shows up, anything the claims emitted would have too.
    ok('issue', 'claim', held)
    ok('issue', 'claim', held, '--renew')
    ok('issue', 'claim', held)
    ok('issue', 'update', tagged, '--title', 'Gets a label (sentinel)')
    text = wait_for(text_out, f'{tagged} changed')
    assert held not in text, text
    # A claim that assigns writes the issue: one update event. First sight of
    # a record prints 'changed'; after that, field transitions.
    ok('issue', 'claim', free)
    wait_for(text_out, f'{free} changed')
    ok('issue', 'release', free)
    wait_for(text_out, f'{free} update assignee: {me["name"]} -> none')
    # Label-only: the CLI names the change, the watch line does not.
    out = ok('issue', 'update', tagged, '--label', 'bug')
    assert out == f'Updated {tagged}: labels=bug\n', out
    out = ok('issue', 'update', tagged, '--add-label', 'bug')
    assert out == f'Updated {tagged}: labels+=bug\n', out
    out = ok('issue', 'update', tagged, '--remove-label', 'bug')
    assert out == f'Updated {tagged}: labels-=bug\n', out
    deadline = time.time() + 10
    while time.time() < deadline:
        lines = [l.split(' ', 1)[1] for l in open(text_out).read().splitlines()]
        if lines.count(f'{tagged} changed') == 4:
            break
        time.sleep(0.1)
    assert lines == [f'{tagged} changed', f'{free} changed',
                     f'{free} update assignee: {me["name"]} -> none'] + [f'{tagged} changed'] * 3, lines
    time.sleep(0.5)
    events = [json.loads(l) for l in open(json_out).read().splitlines()]
    # The stream carries issue records only - never a claims or comments topic.
    assert {e['topic'] for e in events} == {'issues'}, events
    assert [e['action'] for e in events] == ['update'] * 6, events
finally:
    for process in watchers:
        process.kill()
        process.wait()
        process.stderr.close()

# --- 3: bot ownership and rotation.
owner, owner_token = member_token('watch-bot-owner')
_, other_token = member_token('watch-bot-other')


def minted(out):
    # 'lll token create' prints LLL_TOKEN=; 'lll bot' prints the agent
    # prompt's export line (LLL-546). Either way, exactly once.
    lines = [l.removeprefix('export ') for l in out.splitlines() if 'LLL_TOKEN=' in l]
    assert len(lines) == 1 and lines[0].startswith('LLL_TOKEN='), out
    return lines[0][len('LLL_TOKEN='):]


def authenticates(tok):
    return request('/api/collections/members/records?perPage=1', auth=tok)[0] == 200


out = ok('bot', 'bot-watch-contract', '--duration', '3600', as_token=owner_token)
assert 'created bot member bot-watch-contract (kind=bot, owned by watch-bot-owner)' in out, out
first = minted(out)
refused = "rotating bot-watch-contract's token: only the bot's owner or a superuser can do that"
for who in [other_token, first]:  # another full member; the bot itself
    result = cli('bot', 'rotate', 'bot-watch-contract', as_token=who)
    assert result.returncode == 4 and refused in result.stderr, result
    assert authenticates(first), 'a refused rotation stranded the token'
# LLL-546 review: 'lll bot NAME' by a non-owner claims no rotation it did not do.
result = cli('bot', 'bot-watch-contract', as_token=other_token)
assert result.returncode == 4 and refused in result.stderr, result
assert 'rotat' not in result.stdout and 'exists;' not in result.stderr, result
assert authenticates(first), 'a refused rotation stranded the token'
second = minted(ok('bot', 'rotate', 'bot-watch-contract', '--duration', '3600', as_token=owner_token))
assert not authenticates(first) and authenticates(second)
# 'lll bot NAME' on an existing bot is a rotation too.
out = ok('bot', 'bot-watch-contract', '--duration', '3600', as_token=owner_token)
assert 'member bot-watch-contract exists; rotated its token' in out, out
third = minted(out)
assert not authenticates(second) and authenticates(third)
# A superuser rotates any bot; 'lll token create' adds a token and strands none.
fourth = minted(ok('bot', 'rotate', 'bot-watch-contract', '--duration', '3600', as_token=superuser))
assert not authenticates(third) and authenticates(fourth)
if os.environ.get('LLL_ADMIN_EMAIL'):
    result = subprocess.run([binary, 'token', 'create', 'bot-watch-contract', '--duration', '3600'],
        env=dict(os.environ, LLL_URL=api), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert authenticates(minted(result.stdout)) and authenticates(fourth)

# --- 5: LLL-617. A proxy in front of the real server lets the test drop the
# watch's stream, forcing a reconnect, without restarting anything.
class Proxy:
    def __init__(self, upstream):
        self.upstream = upstream
        self.listener = socket.create_server(('127.0.0.1', 0))
        self.port = self.listener.getsockname()[1]
        self.sockets = []
        self.lock = threading.Lock()
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            server = socket.create_connection(self.upstream)
            with self.lock:
                self.sockets += [client, server]
            for a, b in [(client, server), (server, client)]:
                threading.Thread(target=self.pipe, args=(a, b), daemon=True).start()

    @staticmethod
    def pipe(src, dst):
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def drop(self):
        with self.lock:
            dropped, self.sockets = self.sockets, []
        for s in dropped:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    def close(self):
        self.listener.close()
        self.drop()


def stderr_lines(process, sink):
    for line in process.stderr:
        sink.append(line.rstrip('\n'))


def wait_line(lines, text, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if text in lines:
            return
        time.sleep(0.1)
    raise AssertionError(f'{text!r} never appeared on stderr: {lines}')


host, port = urllib.parse.urlsplit(api).hostname, urllib.parse.urlsplit(api).port
proxy = Proxy((host, port))
dead_dir = tempfile.mkdtemp(prefix='watch-dead-token-')
dead_env = dict(env, LLL_URL=f'http://127.0.0.1:{proxy.port}', LLL_TOKEN=fourth,
                LLL_CONFIG_HOME=os.path.join(dead_dir, 'config'))
process = subprocess.Popen([binary, 'watch', '--json'], env=dead_env, cwd=dead_dir,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
lines = []
threading.Thread(target=stderr_lines, args=(process, lines), daemon=True).start()
reconnected = 'realtime: reconnected to the lll server (subscriptions accepted)'
try:
    wait_line(lines, 'watch: ready (query subscription accepted)')
    # A healthy reconnect still reconnects, and the stream still carries events.
    proxy.drop()
    wait_line(lines, reconnected)
    ok('issue', 'update', tagged, '--title', 'Seen after a reconnect')
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(10), ('no event after a healthy reconnect', lines)
    event = json.loads(process.stdout.readline())
    assert event['record']['title'] == 'Seen after a reconnect', event
    # Rotate the bot out from under the watch, then force the reconnect.
    fifth = minted(ok('bot', 'rotate', 'bot-watch-contract', '--duration', '3600', as_token=superuser))
    assert not authenticates(fourth) and authenticates(fifth)
    proxy.drop()
    try:
        code = process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        raise AssertionError(f'watch outlived its rotated token: {lines}')
finally:
    process.kill()
    process.wait()
    proxy.close()
time.sleep(0.2)  # the reader thread drains the last line
assert code == 1, (code, lines)
dead_line = ("realtime: the server rejected this token (401 Unauthorized): it was rotated, "
             "revoked or has expired, so the stream would carry no events; run 'lll login', "
             "or set a fresh LLL_TOKEN ('lll bot rotate bot-NAME' or 'lll token create NAME'), "
             "then start the watch again")
assert lines == ['watch: ready (query subscription accepted)',
                 'realtime: lll server stream lost — reconnecting', reconnected,
                 'realtime: lll server stream lost — reconnecting', dead_line], lines
assert process.stdout.read() == '', 'the dead stream printed an event'
process.stdout.close()

# --- 4: status lines. A fake server drops the stream after one event, fails
# twice with the same error, then accepts again. Only stderr may say so.
stop = threading.Event()
gets = []


class Flaky(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/collections/teams/records?'):
            self.send_response(200)  # connect's token check (LLL-617)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'{}')
            return
        assert self.path == '/api/realtime', self.path
        gets.append(1)
        if len(gets) in (2, 3):
            self.send_response(503)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        n = len(gets)
        self.wfile.write(f'event: PB_CONNECT\ndata: {{"clientId":"c{n}"}}\n\n'.encode())
        self.wfile.flush()
        time.sleep(0.3)  # the subscription POST lands first
        record = {'action': 'update', 'record': {'id': f'r{n}', 'number': n}}
        self.wfile.write(f'event: issues\ndata: {json.dumps(record)}\n\n'.encode())
        self.wfile.flush()
        if n == 1:
            return  # closing the response is the dropped stream
        stop.wait(10)

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Flaky)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
config_home = tempfile.mkdtemp(prefix='watch-contracts-config-')
fake = {k: v for k, v in base.items() if k != 'LLL_TEAM'}
fake.update(LLL_URL=f'http://127.0.0.1:{server.server_port}', LLL_TOKEN='unused', LLL_CONFIG_HOME=config_home)
process = subprocess.Popen([binary, 'watch', '--json'], env=fake,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    stdout = [process.stdout.readline() for _ in range(2)]
finally:
    process.kill()
    rest, stderr = process.communicate(timeout=5)
    stop.set()
    server.shutdown()
    server.server_close()
assert [json.loads(l)['record']['id'] for l in stdout] == ['r1', 'r4'], stdout
assert rest == '', rest
assert stderr.splitlines() == [
    'watch: ready (query subscription accepted)',
    'realtime: lll server stream lost — reconnecting',
    'realtime: reconnect failed: GET /api/realtime: 503 Service Unavailable',
    'realtime: reconnected to the lll server (subscriptions accepted)',
], stderr

# --ready acknowledges with its own wording.
process = subprocess.Popen([binary, 'watch', '--ready'], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
try:
    with selectors.DefaultSelector() as selector:
        selector.register(process.stderr, selectors.EVENT_READ)
        assert selector.select(10), 'watch --ready never acknowledged readiness'
    line = process.stderr.readline()
    assert line == 'watch: ready (agenda subscription accepted)\n', line
finally:
    process.kill()
    process.wait()
    process.stderr.close()

# --- The help text states what the sections above observed, verbatim.
watch_help = ok('watch', '--help')
# Every status line the fake server provoked, as printed; the failure line's
# error text varies, so help shows a placeholder for it.
observed = [l for l in stderr.splitlines() if not l.startswith('realtime: reconnect failed: ')]
for text in observed + [
    'realtime: reconnect failed: <error>',
    "With --ready it reads 'watch: ready (agenda subscription accepted)'",
    'Status lines go to stderr, never stdout',
    '10:42:11 ENG-12 changed',
    'That covers labels, project, description and emoji.',
    'The stream carries issue records only: no comment or claim events.',
    "and 'lll issue claim --renew' print nothing.",
    'Every connect and reconnect checks the token with one read.',
    'watch prints one line naming the fix and exits 1:',
    dead_line.split(': it was')[0] + ': ...',
    'A token rotated while the\nstream is up is caught at the next reconnect',
]:
    assert text in watch_help, f'lll watch --help lost {text!r}'
rotate_help = ok('bot', 'rotate', '--help')
for text in ['Who may rotate: a superuser, or the bot\'s owner',
             'Other members and\nthe bot itself are refused',
             "'lll bot bot-NAME' on an existing bot\nrotates too.",
             "'lll token create bot-NAME' adds a token and strands none."]:
    assert text in rotate_help, f'lll bot rotate --help lost {text!r}'
print('watch contracts: claim events, label-only lines, bot rotation rules, status lines and the dead-token exit pinned')
