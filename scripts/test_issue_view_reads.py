#!/usr/bin/env python3
"""Real CLI reads: overlap, cold-probe coalescing and pre-refactor output."""
import base64
import collections
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

binary = os.path.abspath(sys.argv[1])
record = sys.argv[2:] == ['--record']
# Captured from the published v0.5.0 binary using --record. Regenerate only
# from an independently selected reference, never the candidate under test.
golden_path = Path(__file__).parent / 'fixtures' / 'issue_view_reads.json'
issue_id, member_id, team_id = 'issue0000000001', 'member000000001', 'team00000000001'
stamp = '2020-01-02 12:30:00.000Z'
member = dict(id=member_id, name='viewer', email='viewer@fixture.invalid')
issue = dict(id=issue_id, team=team_id, number=1, title='Read fixture',
             description='A description.\nSecond line.', state='todo', priority=1,
             emoji='🔧', assignee=member_id, labels=['label000000001'],
             blocked_by=[], attachments=['fixture.txt'], created=stamp, updated=stamp,
             expand=dict(team=dict(id=team_id, key='VIEW'), assignee=member,
                         labels=[dict(id='label000000001', name='runtime')]),
             future_field=dict(exact_integer=9007199254740993))
claim = dict(id='claim000000001', issue=issue_id, member=member_id, created=stamp,
             expand=dict(member=member))
doc = dict(id='doc00000000001', team=team_id, slug='linked', title='Linked note',
           kind='wiki', body='Body <example>', area='', paths='', issues=[issue_id],
           created=stamp, updated=stamp, confidence='confirmed', confidence_note='',
           expand=dict(issues=[]))
finding = dict(doc, id='find0000000001', slug='runtime-note', title='Runtime finding',
               kind='finding', area='runtime', issues=[])
comment = dict(id='comment0000001', issue=issue_id, author=member_id,
               body='A comment.', created=stamp, updated=stamp, expand=dict(author=member))
blocker = dict(issue, id='block000000001', number=2, title='Dependent issue')
payload = dict(id=member_id, collectionId='pbc_3572739349', exp=int(time.time()) + 3600)
token = 'e30.' + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=') + '.sig'


class State:
    def __init__(self):
        self.condition = threading.Condition()
        self.active = 0

    def reset(self, case, expected):
        with self.condition:
            assert self.condition.wait_for(lambda: self.active == 0, timeout=5)
            self.case, self.expected = case, expected
            self.counts = collections.Counter()
            self.arrived = set()
            self.errors = []


state = State()


def envelope(items):
    return dict(page=1, totalPages=1, totalItems=len(items), items=items)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Early command failure also closes idle keepalive sockets.

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        filt = query.get('filter', [''])[0]
        route = parsed.path
        if route.endswith('/issues/records'):
            name = 'blocks' if 'blocked_by.id' in filt else 'resolve'
        elif route.endswith('/issues/records/' + issue_id):
            name = 'issue'
        elif route.endswith('/claims/records'):
            name = 'claim'
        elif route.endswith('/docs/records'):
            name = 'findings' if "kind='finding'" in filt else 'docs'
        elif route.endswith('/comments/records'):
            name = 'comments'
        elif route.endswith('/members/records/' + member_id):
            name = 'member'
        else:
            name = 'unexpected'
        independent = name in {'claim', 'docs', 'blocks', 'findings', 'comments'}
        with state.condition:
            state.active += 1
            state.counts[name] += 1
            case = state.case
            if independent:
                state.arrived.add(name)
                state.condition.notify_all()
                if not record and not state.condition.wait_for(
                        lambda: state.arrived == state.expected, timeout=2):
                    state.errors.append('Independent reads did not overlap')
        try:
            assert self.headers.get('Authorization') == 'Bearer ' + token
            status = 200
            rich = case == 'rich'
            if independent and case == 'errors':
                # Comments fail before claims. The mode's old evaluation order
                # must still select the first error, rather than arrival order.
                time.sleep(0.01 if name == 'comments' else 0.08)
                status, body = 503, dict(code=503, message='failed ' + name)
            elif name == 'resolve':
                assert 'team.key' in filt and 'VIEW' in filt
                body = envelope([issue])
            elif name == 'issue':
                body = issue
            elif name == 'claim':
                body = envelope([claim] if rich else [])
            elif name == 'docs':
                assert 'issues.id' in filt
                body = envelope([doc] if rich else [])
            elif name == 'blocks':
                body = envelope([blocker] if rich else [])
            elif name == 'findings':
                assert team_id in filt
                body = envelope([finding] if rich else [])
            elif name == 'comments':
                body = envelope([comment] if rich else [])
            elif name == 'member':
                # All empty replies reach the cold memo before this finishes.
                time.sleep(0.08)
                body = dict(id=member_id)
            else:
                raise AssertionError('Unexpected route: ' + self.path)
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass  # A failed command may exit before its other reads finish.
        except Exception as error:
            with state.condition:
                state.errors.append(str(error))
            self.close_connection = True
        finally:
            with state.condition:
                state.active -= 1
                state.condition.notify_all()


def normalized(text):
    text = re.sub(r'http://127\.0\.0\.1:\d+', '<server>', text)
    return re.sub(r'\b\d+[mhd] ago\b', '<age>', text)


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
results = {}
try:
    with tempfile.TemporaryDirectory(prefix='lll-view-reads-') as config_home:
        env = {key: value for key, value in os.environ.items() if not key.startswith('LLL_')}
        env.update(LLL_URL='http://127.0.0.1:' + str(server.server_port), LLL_TEAM='VIEW',
                   LLL_TOKEN=token, LLL_CONFIG_HOME=config_home)
        expected = None if record else json.loads(golden_path.read_text())
        for case in ('empty', 'rich', 'errors'):
            for mode, args, reads in (
                    ('view', [], {'claim', 'docs', 'blocks', 'findings', 'comments'}),
                    ('raw', ['--raw'], {'findings', 'comments'}),
                    ('json', ['--json'], {'claim', 'docs', 'findings', 'comments'}),
                    ('json-raw', ['--json', '--raw'], {'claim', 'docs', 'findings', 'comments'})):
                state.reset(case, reads)
                result = subprocess.run([binary, 'issue', 'view', 'VIEW-1', *args],
                                        cwd=config_home, env=env, capture_output=True, text=True, timeout=15)
                key = case + '/' + mode
                results[key] = dict(code=result.returncode, stdout=normalized(result.stdout),
                                    stderr=normalized(result.stderr))
                with state.condition:
                    assert state.condition.wait_for(lambda: state.active == 0, timeout=5)
                    assert not state.errors, state.errors
                    if not record:
                        assert results[key] == expected[key], (key, results[key], expected[key])
                        assert state.arrived == reads, (key, state.arrived)
                        assert all(state.counts[name] == 1 for name in reads), state.counts
                        assert state.counts['member'] == (1 if case == 'empty' else 0), state.counts
                        assert sum(state.counts.values()) == 2 + len(reads) + (case == 'empty'), state.counts
                if case != 'errors':
                    assert result.returncode == 0, result.stderr
                else:
                    assert result.returncode != 0
        if record:
            golden_path.parent.mkdir(exist_ok=True)
            golden_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + '\n')
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
if record:
    print('Captured pre-refactor output from the reference binary')
else:
    print('Issue view: overlapping mode-specific reads, one cold identity probe, byte-stable output and deterministic partial-output errors passed')
