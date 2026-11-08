#!/usr/bin/env python3
"""Owned lifecycle through the installed CLI and the real collection rules."""
import http.server
import json
import os
import pty
import select
import time
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
assert urllib.parse.urlsplit(api).hostname == '127.0.0.1', 'requires a scratch board'
owner = os.environ['LLL_TOKEN']
jwt = re.compile(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')


def request(path, body=None, token=None, method=None):
    req = urllib.request.Request(api + path, data=None if body is None else json.dumps(body).encode(),
        method=method, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (owner if token is None else token)})
    try:
        response = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        data = response.read()
        return response.status, json.loads(data) if data else None


with tempfile.TemporaryDirectory(prefix='lll-owner-bots-') as home:
    env = dict(os.environ, LLL_URL=api, LLL_TEAM='ABSENT-LIFECYCLE-CONTEXT', LLL_CONFIG_HOME=home)

    def cli(*args, token=None, expected=0, extra=None):
        result = subprocess.run([binary, *args], env=env | ({'LLL_TOKEN': token} if token is not None else {}) | (extra or {}),
            capture_output=True, text=True, timeout=30)
        assert result.returncode == expected, f'{args[:3]} exit {result.returncode}, expected {expected}'
        if expected:
            assert not result.stdout and not jwt.search(result.stderr)
        return result

    def packet(result):
        assert not result.stderr
        return json.loads(result.stdout)

    def auth(token):
        # Auth-refresh is a POST and the existing read-only write guard refuses it.
        # This authenticated GET validates the token without requesting a write.
        return request('/api/lll/access', token=token)[0]

    parent = packet(cli('bot', 'create', 'bot-lifecycle-parent', '--json'))
    child = packet(cli('bot', 'create', 'bot-lifecycle-child', '--json', token=parent['token']))
    cli('team', 'create', '--key', 'LIFEBOT', '-n', 'Bot lifecycle')
    issue = packet(cli('issue', 'create', '-t', 'Keep the work', '-b', 'Keep the body', '--team', 'LIFEBOT', '--json', token=child['token']))
    comment = packet(cli('issue', 'comment', issue['key'], '-b', 'Keep the finding', '--json', token=child['token']))
    cli('issue', 'claim', issue['key'], '--agent', 'lifecycle-worker', token=child['token'])
    cli('bot', 'disable', parent['name'], token=parent['token'], expected=4)
    cli('bot', 'remove', child['name'], '--force', '--yes', token=parent['token'], expected=4)
    disabled = packet(cli('bot', 'disable', parent['name'], '--json'))
    assert set(disabled) == {'id', 'name', 'disabled'} and disabled['disabled'] is True
    retired, narrowed = auth(parent['token']), auth(child['token'])
    assert (retired, narrowed) == (401, 200), f'auth status after disable: parent={retired}, child={narrowed}'
    assert request('/api/collections/issues/records/' + issue['id'], token=child['token'])[0] == 404
    before = packet(cli('issue', 'view', issue['key'], '--json'))
    assert before['description'] == 'Keep the body' and before['claim']['member']
    cli('bot', 'remove', parent['name'], '--json', expected=4)
    removed = packet(cli('bot', 'delete', parent['name'], '--force', '--yes', '--json'))
    assert set(removed) == {'id', 'name', 'removed', 'had_references'}
    assert removed['removed'] and removed['had_references'] and auth(child['token']) == 401
    child_record = request('/api/collections/members/records/' + before['claim']['member'])[1]
    assert child_record['owner'] and not child_record['created_by']
    assert child_record['scope'] == 'teams' and child_record['teams'] == [] and child_record['mode'] == 'ro'
    cli('bot', 'remove', child['name'], '--json', expected=4)
    packet(cli('bot', 'remove', child['name'], '--force', '--yes', '--json'))
    kept = packet(cli('issue', 'view', issue['key'], '--json'))
    assert kept['description'] == 'Keep the body' and not kept['creator'] and not kept['assignee']
    assert kept['claim'] is None
    assert request('/api/collections/comments/records/' + comment['id'])[1]['body'] == 'Keep the finding'

    code, _ = request('/api/collections/members/records', {'name': 'lifecycle-outsider', 'email': 'lifecycle-outsider@example.invalid',
        'password': 'isolated-lifecycle-password', 'passwordConfirm': 'isolated-lifecycle-password'})
    assert code == 200
    code, login = request('/api/collections/members/auth-with-password',
        {'identity': 'lifecycle-outsider@example.invalid', 'password': 'isolated-lifecycle-password'})
    assert code == 200
    foreign = packet(cli('bot', 'create', 'bot-lifecycle-foreign', '--json', token=login['token']))
    for action in ['disable', 'remove']:
        cli('bot', action, foreign['name'], '--json', expected=4)
        assert auth(foreign['token']) == 200
    unused = packet(cli('bot', 'create', 'bot-lifecycle-unused', '--json'))
    assert packet(cli('bot', 'remove', unused['name'], '--json', '--yes'))['had_references'] is False
    assert auth(unused['token']) == 401

    # Real terminal stdin, with separate stdout/stderr: cancelling cannot delete,
    # and accepting --json must leave stdout as exactly one receipt.
    interactive = packet(cli('bot', 'create', 'bot-lifecycle-terminal', '--json'))
    def terminal_remove(answer, expected):
        master, slave = pty.openpty()
        process = subprocess.Popen([binary, 'bot', 'remove', interactive['name'], '--json'],
            stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        os.close(slave)
        diagnostic = b''
        try:
            deadline = time.monotonic() + 20
            while b'[y/N]' not in diagnostic:
                assert time.monotonic() < deadline, 'terminal confirmation did not appear'
                ready, _, _ = select.select([process.stderr], [], [], 1)
                if ready:
                    part = os.read(process.stderr.fileno(), 4096)
                    assert part, 'process exited before confirmation'
                    diagnostic += part
            os.write(master, answer.encode() + b'\n')
            stdout, stderr = process.communicate(timeout=20)
            assert process.returncode == expected, f"terminal exit {process.returncode}, expected {expected}"
            assert b'remove bot ' in diagnostic and not jwt.search((diagnostic + stderr).decode())
            return stdout
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.communicate()
    assert terminal_remove('n', 4) == b''
    assert auth(interactive['token']) == 200
    assert json.loads(terminal_remove('yes', 0))['removed'] is True
    assert auth(interactive['token']) == 401

    class Unsupported(http.server.BaseHTTPRequestHandler):
        writes = 0
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"service":"lll","version":"1.5.0","capabilities":[]}')
        def do_POST(self):
            type(self).writes += 1
            self.send_error(500)
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Unsupported)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for action in ['disable', 'remove']:
            refused = cli('bot', action, 'bot-not-sent', '--json', expected=1,
                extra={'LLL_URL': f'http://127.0.0.1:{server.server_port}'})
            assert 'upgrade the server' in refused.stderr
        assert Unsupported.writes == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

print('Owner bot lifecycle: no team/admin login, owner/creator boundaries, retired tokens, narrowed workers, referenced/forced removal, kept work, released claims and unsupported no-write refusal passed')
