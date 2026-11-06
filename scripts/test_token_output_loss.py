#!/usr/bin/env python3
"""A closed pipe reports committed credential loss instead of SIGPIPE."""
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
assert urllib.parse.urlsplit(api).hostname == '127.0.0.1', 'requires an isolated loopback board'
env = dict(os.environ, LLL_URL=api)
jwt = re.compile(rb'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')


def call(path, token=None, body=None):
    request = urllib.request.Request(api + path, data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (token or env['LLL_TOKEN'])})
    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


def credential(*args):
    result = subprocess.run([binary, 'bot', *args, '--env'], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stderr, 'control credential failed'
    exports = dict(shlex.split(line)[1].split('=', 1) for line in result.stdout.splitlines())
    return exports['LLL_TOKEN']


def closed_stdout(*args):
    process = subprocess.Popen([binary, *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.stdout.close()
    process.stdout = None
    _, error = process.communicate(timeout=30)
    assert process.returncode == 1, f'closed stdout exit={process.returncode}, stderr_empty={not error}'
    assert b'Error: writing output:' in error and not jwt.search(error)
    return error


# First failure on the published baseline: the member commits before the
# token write receives SIGPIPE. Never log a credential or the captured packet.
error = closed_stdout('bot', 'create', 'bot-output-lost-create', '--env')
assert b'not written anywhere' in error and b'lll bot rotate bot-output-lost-create' in error
code, rows = call('/api/collections/members/records?filter=' + urllib.parse.quote('name="bot-output-lost-create"'))
assert code == 200 and len(rows['items']) == 1
credential('rotate', 'bot-output-lost-create')
old = credential('create', 'bot-output-lost-rotate')
error = closed_stdout('bot', 'rotate', 'bot-output-lost-rotate', '--env')
assert b'not written anywhere' in error and b'lll bot rotate bot-output-lost-rotate' in error
assert call('/api/collections/members/auth-refresh', old, {})[0] == 401
new = credential('rotate', 'bot-output-lost-rotate')
assert call('/api/collections/members/auth-refresh', new, {})[0] == 200
closed_stdout('--help')
normal = subprocess.run([binary, '--version'], env=env, capture_output=True, text=True, timeout=10)
assert normal.returncode == 0 and normal.stdout.startswith('lll ') and not normal.stderr
# A notice on an unwritable stderr must not lose the successfully claimed
# issue's stdout key. Only SIGPIPE is ignored; normal process signals remain.
created = subprocess.run([binary, 'issue', 'create', '-t', 'Output notice control', '--json'],
                         env=env, capture_output=True, text=True, timeout=30)
assert created.returncode == 0
issue = json.loads(created.stdout)
team = issue['expand']['team']['key']
key = team + '-' + str(issue['number'])
process = subprocess.Popen([binary, 'issue', 'next', '--claim', '--team', team], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
process.stderr.close()
process.stderr = None
answer, _ = process.communicate(timeout=30)
assert process.returncode == 0 and answer.decode().strip() == key, 'closed stderr lost the claimed key'
print('Token output loss: create/rotate recoverable with exit1, no credential on stderr, old token retired; ordinary stdout failure and closed-stderr claim key passed')
