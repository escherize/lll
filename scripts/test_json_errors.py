#!/usr/bin/env python3
"""Typed stderr diagnostics through the native CLI, including older servers."""
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.parse

binary, api = sys.argv[1:]
assert urllib.parse.urlsplit(api).hostname == '127.0.0.1'

with tempfile.TemporaryDirectory(prefix='lll-json-errors-') as home:
    env = dict(os.environ, LLL_URL=api, LLL_CONFIG_HOME=home, LLL_TEAM='ERRJSON')

    def run(*args, extra=None, machine=True):
        return subprocess.run([binary, *(['--json-errors'] if machine else []), *args],
            env=env | (extra or {}), capture_output=True, text=True, timeout=30)

    def refusal(result, code, reason, status=None, stdout=''):
        assert result.returncode == code, (result.returncode, code)
        assert result.stdout == stdout, 'diagnostic changed stdout'
        packet = json.loads(result.stderr)
        assert set(packet) == {'error'}
        error = packet['error']
        assert set(error) == {'reason', 'exit_code', 'http_status', 'server_code', 'output_failed', 'recovery'}
        assert error['exit_code'] == code and error['reason'] == reason, error
        if status is not None:
            assert error['http_status'] == status
        assert not error['output_failed'] and error['recovery'] == ''
        return error

    refusal(run('not-a-command'), 2, 'usage', 0)
    parts = env['LLL_TOKEN'].split('.')
    assert len(parts) == 3
    parts[2] = ('A' if parts[2][0] != 'A' else 'B') + parts[2][1:]
    refusal(run('whoami', extra={'LLL_TOKEN': '.'.join(parts)}), 6, 'not_authenticated')
    assert run('team', 'create', '--key', 'ERRJSON', '-n', 'Structured errors').returncode == 0
    empty = run('issue', 'next')
    refusal(empty, 5, 'nothing_to_do', 0)
    created = run('issue', 'create', '-t', 'Typed refusals', '--json')
    assert created.returncode == 0 and not created.stderr
    key = json.loads(created.stdout)['key']
    for args in [('issue', 'release', key), ('issue', 'claim', key, '--renew')]:
        error = refusal(run(*args), 4, 'not_claimed', 0)
        assert error['server_code'] == ''
    refusal(run('issue', 'view', 'ERRJSON-999999'), 3, 'not_found')
    refusal(run('issue', 'update', key, '-t', 'Never applied', '--if-unchanged-since',
                '2000-01-01T00:00:00Z'), 4, 'conflict')
    # The opt-in is a prefix, never an extractor that steals a literal body.
    body = run('issue', 'comment', key, '-b', '--json-errors', '--json', machine=False)
    assert body.returncode == 0 and json.loads(body.stdout)['body'] == '--json-errors'
    ordinary = run('issue', 'release', key, machine=False)
    assert ordinary.returncode == 4 and ordinary.stderr.startswith('Error: ')

    class Answers(http.server.BaseHTTPRequestHandler):
        status = 409
        code = ''
        calls = 0
        secret = 'do-not-reflect-password-or-token'

        def do_GET(self):
            type(self).calls += 1
            if self.path == '/.well-known/lll':
                data = {'service': 'lll', 'version': '99.0.0'}
                status = 200
            else:
                status = type(self).status
                data = {'status': status, 'message': self.secret,
                        'data': {'code': type(self).code}}
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Answers)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        other = {'LLL_URL': f'http://127.0.0.1:{server.server_port}'}
        # Raw api deliberately preserves its body even on --fail. Its status
        # notice and skew warning must not corrupt the diagnostic document.
        for status, code, reason in [(401, '', 'not_authenticated'), (404, '', 'not_found'),
                (409, '', 'conflict'), (412, '', 'conflict'), (403, '', 'refused'),
                (400, 'not_claimed', 'not_claimed'), (400, 'claim_changed', 'conflict'),
                (403, 'future_unknown_reason', 'refused'), (500, '', 'server_error')]:
            Answers.status, Answers.code = status, code
            result = run('api', 'GET', '/failure', '--fail', extra=other)
            expected = {401: 6, 404: 3, 409: 4, 412: 4, 403: 4, 400: 4, 500: 1}[status]
            packet = refusal(result, expected, reason, status, stdout=result.stdout)
            assert json.loads(result.stdout)['message'] == Answers.secret
            assert Answers.secret not in result.stderr
            assert packet['server_code'] == (code if code in {'not_claimed', 'claim_changed'} else '')
        before = Answers.calls
        refusal(run('issue', 'list', '--not-a-flag', extra=other), 2, 'usage', 0)
        assert Answers.calls == before, 'usage validation made an HTTP request'
        Answers.status, Answers.code = 409, ''
        lost = subprocess.Popen([binary, '--json-errors', 'api', 'GET', '/failure', '--fail'],
            env=env | other, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        lost.stdout.close()
        lost.stdout = None
        _, diagnostic = lost.communicate(timeout=30)
        assert lost.returncode == 4, 'output failure replaced the original refusal exit'
        error = json.loads(diagnostic)['error']
        assert error['reason'] == 'conflict' and error['output_failed']
        assert Answers.secret.encode() not in diagnostic
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    lost = subprocess.Popen([binary, '--json-errors', 'bot', 'create',
        'bot-error-output-lost', '--json'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lost.stdout.close()
    lost.stdout = None
    _, diagnostic = lost.communicate(timeout=30)
    assert lost.returncode == 1
    error = json.loads(diagnostic)['error']
    assert error['reason'] == 'error' and error['output_failed']
    assert 'lll bot rotate bot-error-output-lost' in error['recovery']
    assert not re.search(rb'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', diagnostic)
    claimed = subprocess.Popen([binary, '--json-errors', 'issue', 'next', '--claim'], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    claimed.stderr.close()
    claimed.stderr = None
    answer, _ = claimed.communicate(timeout=30)
    assert claimed.returncode == 0 and answer.decode().strip() == key

print('JSON errors: native typed refusals, unchanged exits/stdout, secret-free diagnostics, old-code fallback and no-I/O usage passed')
