#!/usr/bin/env python3
"""Issue containment converges on both parents, the child and board cards."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse

from browser_session import new_session, open_session, require_result

binary, api, board = sys.argv[1:]
assert all(urllib.parse.urlsplit(url).hostname == '127.0.0.1' for url in (api, board)), 'requires isolated loopback listeners'
env = dict(os.environ, LLL_URL=api, LLL_TEAM='TREEUI')
cookie = 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN']


def cli(*args):
    result = subprocess.run([binary, *args], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def create(title, *args):
    record = json.loads(cli('issue', 'create', '-t', title, *args, '--json'))
    return 'TREEUI-' + str(record['number'])


class Stream:
    def __init__(self, key):
        request = urllib.request.Request(board + '/events?page=issue&key=' + key, headers={'Cookie': cookie})
        self.response = urllib.request.urlopen(request, timeout=30)
        self.events = queue.Queue()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        data = b''
        try:
            for line in self.response:
                data += line
                if line == b'\n':
                    self.events.put(data.decode())
                    data = b''
        except Exception as error:
            self.events.put(error)

    def until(self, predicate):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            event = self.events.get(timeout=max(0.01, deadline - time.monotonic()))
            assert isinstance(event, str), str(event)
            if 'id="issue-detail"' in event and predicate(event):
                return event
        raise AssertionError('tree view did not converge')


cli('team', 'create', '--key', 'TREEUI', '-n', 'Issue tree UI verification')
first = create('First parent')
second = create('Second parent')
child = create('Child with a long title that wraps naturally on a narrow screen', '--parent', first)
streams = []
try:
    a, b, c = (Stream(key) for key in (first, second, child))
    streams += [a, b, c]
    a.until(lambda text: '0/1 done' in text and child in text)
    b.until(lambda text: 'issue-children' not in text)
    c.until(lambda text: 'First parent' in text and 'issue-parent' in text)
    cli('issue', 'update', child, '--parent', second)
    a.until(lambda text: 'issue-children' not in text)
    b.until(lambda text: '0/1 done' in text and child in text)
    c.until(lambda text: 'Second parent' in text and 'First parent' not in text)
    cli('issue', 'update', second, '--title', 'Renamed second parent')
    c.until(lambda text: 'Renamed second parent' in text)
    cli('issue', 'close', child)
    b.until(lambda text: '1/1 done' in text)
    cli('issue', 'update', child, '--state', 'todo')
    b.until(lambda text: '0/1 done' in text)
    fresh = Stream(second)
    streams.append(fresh)
    fresh.until(lambda text: '0/1 done' in text and child in text)
    request = urllib.request.Request(board + '/t/TREEUI/issue/' + second + '?raw', headers={'Cookie': cookie})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode()
    assert 'Children (0/1 done)' in raw and child in raw
    victim = create('Parent to detach')
    detached = create('Surviving detached child', '--parent', victim)
    parent_stream, child_stream = Stream(victim), Stream(detached)
    streams += [parent_stream, child_stream]
    parent_stream.until(lambda text: '0/1 done' in text)
    child_stream.until(lambda text: 'Parent to detach' in text)
    cli('issue', 'delete', victim, '--yes')
    parent_stream.until(lambda text: 'was deleted' in text)
    child_stream.until(lambda text: 'issue-parent' not in text)
    print('Tree SSE: old/new parent, child parent title, child state and reconnect converge')
finally:
    for stream in streams:
        stream.response.close()

if shutil.which('playwright-cli'):
    session = new_session()
    try:
        open_session(session, board + '/?board_token=' + os.environ['LLL_TEST_BOARD_TOKEN'])
        code = (Path(__file__).resolve().parent / 'browser_issue_tree.js').read_text()
        result = subprocess.run(['playwright-cli', '-s=' + session, 'run-code', code],
                                capture_output=True, text=True, timeout=90)
        Path('/tmp/lll-177-tree-browser.log').write_text(result.stdout + result.stderr)
        require_result(result, 'Issue tree browser passed', board)
        print('Tree browser: live progress preserves drafts, keyboard links, desktop/mobile and board cards passed')
    finally:
        subprocess.run(['playwright-cli', '-s=' + session, 'close'], capture_output=True, timeout=15)
