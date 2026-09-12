#!/usr/bin/env python3
"""Actual SSE snapshots, selective description updates and reconnects."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
from browser_session import new_session, open_session, require_result
import sys
import threading
import urllib.request

binary, api, board = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='SSE58')
cookie = 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN']


def cli(*args):
    p = subprocess.run([binary, *args], env=env, text=True, capture_output=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return p.stdout


class Stream:
    def __init__(self, key):
        request = urllib.request.Request(board + '/events?page=issue&key=' + key, headers={'Cookie': cookie})
        self.response = urllib.request.urlopen(request, timeout=25)
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

    def until(self, marker):
        for _ in range(100):
            event = self.events.get(timeout=20)
            assert isinstance(event, bytes), str(event)
            if marker in event:
                return event
        raise AssertionError('missing SSE marker: ' + repr(marker))

    def no_description(self):
        while True:
            try:
                event = self.events.get(timeout=0.3)
            except queue.Empty:
                return
            assert isinstance(event, bytes), str(event)
            assert b'id="issue-description"' not in event, 'unchanged description resent'


cli('team', 'create', '-k', 'SSE58', '-n', 'Issue stream verification')
source = ('large description & < >\n' * 5000)[:100000]
record = json.loads(cli('issue', 'create', 'Stream lifecycle', '-d', source, '--json'))
key = 'SSE58-' + str(record['number'])
a = Stream(key)
initial = a.until(b'id="issue-description"')
assert initial.count(b'large description') == source.count('large description')
cli('issue', 'update', key, '--priority', 'high', '--title', 'Metadata one')
metadata = a.until(b'Metadata one')
assert b'large description' not in metadata and len(metadata) < len(initial) // 4
assert b'id="issue-description"' not in metadata
a.no_description()
# A second connection receives its own fresh snapshot without refreshing A.
b = Stream(key)
assert b'large description' in b.until(b'id="issue-description"')
a.no_description()
cli('issue', 'update', key, '-d', 'Replacement **description**')
for stream in (a, b):
    assert b'Replacement <strong>description</strong>' in stream.until(b'id="issue-description"')
cli('issue', 'update', key, '-d', '')
for stream in (a, b):
    assert b'hidden' in stream.until(b'id="issue-description"')
# Fresh stream after an offline edit must have the current description.
cli('issue', 'update', key, '-d', 'After reconnect')
c = Stream(key)
assert b'After reconnect' in c.until(b'id="issue-description"')
cli('issue', 'update', key, '--title', 'Metadata after reconnect')
assert b'After reconnect' not in c.until(b'Metadata after reconnect')
c.no_description()
# An absent issue gets an explicit empty snapshot, not an endless blank stream.
missing = Stream('SSE58-99999')
assert b'was deleted' in missing.until(b'id="issue-detail"')
assert b'hidden' in missing.until(b'id="issue-description"')
cli('issue', 'update', key, '-d', '# Diagram\n\n```mermaid\ngraph LR\n  A --> B\n```\n\nKeep this paragraph.')
print(f'Issue stream: metadata {len(metadata)} bytes; initial description {len(initial)} bytes; edit, clear, independent snapshots and reconnect passed')

if shutil.which('playwright-cli'):
    session = new_session()
    try:
        open_session(session, board + '/?board_token=' + os.environ['LLL_TEST_BOARD_TOKEN'])
        result = subprocess.run(['playwright-cli', '-s=' + session, 'run-code', Path('scripts/browser_issue_stream.js').read_text()], text=True, capture_output=True, timeout=90)
        output = result.stdout + result.stderr
        Path('/tmp/lll-58-browser-gate.log').write_text(output)
        require_result(result, 'Issue stream browser passed', board)
        print('Issue stream browser: retained Mermaid DOM and drafts; desktop/mobile screenshots passed')
    finally:
        subprocess.run(['playwright-cli', '-s=' + session, 'close'], capture_output=True, timeout=15)

# Delete must clear both metadata and the separately owned description.
victim = json.loads(cli('issue', 'create', 'Delete stream', '-d', 'Remove this body', '--json'))
victim_key = 'SSE58-' + str(victim['number'])
deleted = Stream(victim_key)
assert b'Remove this body' in deleted.until(b'id="issue-description"')
cli('issue', 'delete', victim_key, '--force')
assert b'id="issue-detail"' in deleted.until(b'was deleted')
assert b'hidden' in deleted.until(b'id="issue-description"')
print('Issue stream deletion: metadata tombstone and description clear passed')
