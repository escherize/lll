#!/usr/bin/env python3
"""Claim-only realtime transitions and actual board controls."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
from browser_session import new_session, open_session
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

binary, api, board = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='CL185')
cookie = 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN']


def cli(*args):
    p = subprocess.run([binary, *args], env=env, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return p.stdout


def request(path, body=None, method=None, web=False):
    headers = {'Cookie': cookie} if web else {'Authorization': 'Bearer ' + env['LLL_TOKEN']}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request((board if web else api) + path,
        data=None if body is None else json.dumps(body).encode(), method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


class Stream:
    def __init__(self, query):
        self.response = urllib.request.urlopen(urllib.request.Request(board + '/events?' + query,
            headers={'Cookie': cookie}), timeout=25)
        self.events = queue.Queue()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        data = b''
        try:
            for line in self.response:
                data += line
                if line == b'\n':
                    self.events.put(data)
                    data = b''
        except Exception as error:
            self.events.put(error)

    def until(self, predicate):
        for _ in range(100):
            event = self.events.get(timeout=20)
            assert isinstance(event, bytes), str(event)
            if predicate(event):
                return event
        raise AssertionError('missing claim stream transition')


cli('team', 'create', '-k', 'CL185', '-n', 'Live claims')
record = json.loads(cli('issue', 'create', 'Live claim controls', '--json'))
key = 'CL185-1'
record_path = '/api/collections/issues/records/' + record['id']
request(record_path, {'work_branch': 'claim-review', 'work_host': 'test', 'work_path': '/review'}, 'PATCH')
cli('member', 'add', '-n', 'Unrelated claim assignee')
members = json.loads(cli('member', 'list', '--json'))['items']
other = next(m for m in members if m['name'] == 'Unrelated claim assignee')
issue_stream = Stream('page=issue&key=' + key)
board_stream = Stream('page=board&team=CL185')
issue_stream.until(lambda e: b'id="claim-form"' in e)
board_stream.until(lambda e: b'id="board"' in e and b'card-claim' not in e)
cli('issue', 'claim', key)
held = json.loads(cli('issue', 'view', key, '--json'))['claim']
issue_stream.until(lambda e: b'id="release-form"' in e)
board_stream.until(lambda e: b'class="card-claim"' in e)
assert held['expand']['member']['name'].encode() in request('/issue/' + key + '?raw', web=True)

# Change assignment independently, then release only the hold. No issue PATCH
# follows this release, so only a claims subscription can refresh the UI.
request(record_path, {'assignee': other['id']}, 'PATCH')
issue_stream.until(lambda e: ('value="' + other['id'] + '" selected').encode() in e)
before = json.loads(request(record_path))
cli('issue', 'release', key)
after = json.loads(request(record_path))
assert after['updated'] == before['updated'] and after['assignee'] == other['id']
issue_stream.until(lambda e: b'id="claim-form"' in e and b'(last seen)' in e)
board_stream.until(lambda e: b'id="board"' in e and b'card-claim' not in e and b'(last seen)' in e)

# New connections get current state without requiring a subsequent mutation.
cli('issue', 'claim', key)
issue_stream.until(lambda e: b'id="release-form"' in e)
board_stream.until(lambda e: b'class="card-claim"' in e)
Stream('page=issue&key=' + key).until(lambda e: b'id="release-form"' in e)
Stream('page=board&team=CL185').until(lambda e: b'class="card-claim"' in e)
cli('issue', 'release', key)
print('Board claims: claim-only release updates issue/card/work-site, unrelated assignment preserved, reconnect snapshots and raw holder passed')

if shutil.which('playwright-cli'):
    session = new_session()
    try:
        open_session(session, board + '/?board_token=' + os.environ['LLL_TEST_BOARD_TOKEN'])
        p = subprocess.run(['playwright-cli', '-s=' + session, 'run-code', Path('scripts/browser_claims.js').read_text()], capture_output=True, text=True, timeout=100)
        output = p.stdout + p.stderr
        Path('/tmp/lll-185-browser.log').write_text(output)
        assert '### Error' not in output and 'Board claim controls passed' in output, 'see /tmp/lll-185-browser.log'
        final = json.loads(cli('issue', 'view', key, '--json'))
        assert final['claim'] is None and final['title'] == 'Live claim controls'
        print('Board claim browser: two views, named actor, keyboard release, stale form rejection, retained drafts and responsive screenshots passed')
    finally:
        subprocess.run(['playwright-cli', '-s=' + session, 'close'], capture_output=True, timeout=15)

# The board must still hide controls and reject writes for an archived team.
cli('team', 'archive', 'CL185')
html = request('/issue/' + key, web=True)
assert b'id="claim-form"' not in html and b'id="release-form"' not in html
data = urllib.parse.urlencode({'key': key}).encode()
req = urllib.request.Request(board + '/claim', data=data,
    headers={'Cookie': cookie, 'Content-Type': 'application/x-www-form-urlencoded'})
with urllib.request.urlopen(req, timeout=20) as response:
    assert b'archived' in response.read()
assert json.loads(cli('issue', 'view', key, '--json'))['claim'] is None

# Put a visible card's hold on page two of the claims query. This pins the
# expanded batch lookup independently of the separately tracked board limit.
team = json.loads(request('/api/collections/teams/records', {'key': 'CPAGE', 'name': 'Claim pages'}))
first = json.loads(request('/api/collections/issues/records', {'team': team['id'], 'title': 'Last-page holder', 'state': 'todo'}))
def seed(n):
    issue = first if n == 0 else json.loads(request('/api/collections/issues/records',
        {'team': team['id'], 'title': 'Pagination fixture ' + str(n), 'state': 'todo'}))
    return request('/api/collections/claims/records', {'id': 'zzzzzzzzzzzzzzz' if n == 0 else 'c' + str(n).zfill(14),
        'issue': issue['id'], 'member': other['id']})
with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(seed, range(201)))
html = request('/t/CPAGE/', web=True).decode()
card = html.split('id="issue-' + first['id'] + '"', 1)[1].split('</a>', 1)[0]
assert 'Claimed: Unrelated claim assignee' in card
print('Board claim pages: expanded holder from page two, scoped to the displayed team, passed')
