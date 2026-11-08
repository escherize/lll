#!/usr/bin/env python3
"""Current comment/claim cursor reads on an owned, isolated board."""
import datetime
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
server = str(Path(sys.argv[2]).resolve()) if len(sys.argv) > 2 else binary


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def canonical(stamp):
    parsed = datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    assert stamp == parsed.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


with tempfile.TemporaryDirectory(prefix='lll-bulk-reads-') as temporary:
    root = Path(temporary)
    (root / 'home').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root / 'home'), USER='bulk-owner', LLL_TEAM='BULKREAD',
               LLL_BIND='127.0.0.1', LLL_URL=f'http://127.0.0.1:{free_port()}',
               LLL_ADMIN_EMAIL='bulk@example.invalid', LLL_ADMIN_PASSWORD='bulk-fixture-password',
               LLL_BOARD_TOKEN='bulk-fixture-board')
    log = root / 'server.log'
    with log.open('w') as output:
        child = subprocess.Popen([server, 'up', '--no-open', '--pb-dir', str(root / 'data'),
                                  '--port', str(free_port())], env=env, cwd=root,
                                 stdout=output, stderr=subprocess.STDOUT)
    try:
        api = wait_for_endpoints(log)['db_url']
        env['LLL_URL'] = api

        def request(path, body=None, method=None, token=None):
            req = urllib.request.Request(api + path, method=method,
                data=None if body is None else json.dumps(body).encode(),
                headers={'Content-Type': 'application/json',
                         'Authorization': 'Bearer ' + (env.get('LLL_TOKEN', '') if token is None else token)})
            try:
                response = urllib.request.urlopen(req, timeout=20)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None

        code, auth = request('/api/collections/_superusers/auth-with-password',
                            {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})
        assert code == 200, 'fixture administrator authentication failed'
        admin = auth['token']
        code, members = request('/api/collections/members/records', token=admin)
        assert code == 200
        owner = next(m for m in members['items'] if m['name'] == 'bulk-owner')
        code, auth = request('/api/collections/members/impersonate/' + owner['id'], {'duration': 3600}, token=admin)
        assert code == 200
        env['LLL_TOKEN'] = auth['token']

        def cli(*args, code=0, token=None, team='BULKREAD'):
            current = dict(env, LLL_TEAM=team, LLL_TOKEN=env['LLL_TOKEN'] if token is None else token)
            p = subprocess.run([binary, *args], env=current, cwd=root, capture_output=True, text=True, timeout=30)
            assert p.returncode == code, (args, p.returncode, p.stderr)
            if code:
                assert not p.stdout, 'refused bulk command printed partial stdout'
                return p
            return json.loads(p.stdout) if '--json' in args else p.stdout

        # Fail on the unfixed binary before creating fixtures for a missing noun.
        cli('comment', 'list', '--help')
        cli('claim', 'list', '--help')
        cli('team', 'create', '--key', 'BULKOTHER', '-n', 'Other bulk reads')
        for project in ('Alpha', 'Beta', 'Empty'):
            cli('project', 'create', project)
        cli('project', 'create', 'Alpha', team='BULKOTHER')
        targets = [cli('issue', 'create', f'Bulk target {n}', '--project', 'Alpha', '--json') for n in range(4)]
        other_project = cli('issue', 'create', 'Other project', '--project', 'Beta', '--json')
        other_team = cli('issue', 'create', 'Other team', '--project', 'Alpha', '--json', team='BULKOTHER')
        for issue in targets:
            for body in ('First progress', 'Second progress: 引用 📎\n"quoted"'):
                cli('issue', 'comment', issue['key'], '-b', body, '--json')
        cli('issue', 'comment', other_project['key'], '-b', 'Not Alpha')
        cli('issue', 'comment', other_team['key'], '-b', 'Not this team', team='BULKOTHER')
        for issue in targets[:3] + [other_project, other_team]:
            cli('issue', 'claim', issue['key'], '--agent', 'bulk-reader-proof', team='BULKOTHER' if issue == other_team else 'BULKREAD')

        def truth(collection):
            expression = 'issue.project = "' + targets[0]['project'] + '"'
            code, page = request('/api/collections/' + collection + '/records?sort=id&perPage=500&filter=' + urllib.parse.quote(expression))
            assert code == 200
            return page['items']

        def collect(noun, first):
            result = list(first['items'])
            seen_cursors = set()
            page = first
            while page['next_cursor']:
                assert page['next_cursor'] not in seen_cursors, 'cursor loop'
                seen_cursors.add(page['next_cursor'])
                last = result[-1]['id']
                remaining = [r for r in truth(noun + 's') if r['id'] > last]
                page = cli(noun, 'list', '--project', 'Alpha', '--limit', '2', '--since', page['next_cursor'], '--json')
                assert page['page'] == 1 and page['perPage'] == 2
                assert page['totalItems'] == len(remaining)
                assert [i['id'] for i in page['items']] == [i['id'] for i in remaining[:2]]
                result.extend(page['items'])
            assert len({r['id'] for r in result}) == len(result), 'duplicate record under keyset pagination'
            return result

        initial = truth('comments')
        first = cli('comment', 'list', '--project', 'Alpha', '--limit', '2', '--json')
        assert first['totalItems'] == 8 and len(first['items']) == 2 and first['next_cursor']
        assert first['items'][0]['author'] == owner['id'] and first['items'][0]['author_name'] == owner['name']
        assert first['items'][0]['key'].startswith('BULKREAD-')
        listed_comment = first['items'][0]
        viewed_comments = cli('issue', 'view', listed_comment['key'], '--json')['comments']
        viewed_comment = next(c for c in viewed_comments if c['id'] == listed_comment['id'])
        for field in ('id', 'issue', 'author', 'author_name', 'server_record', 'body', 'created', 'updated'):
            assert listed_comment[field] == viewed_comment[field]
        for field in ('agent', 'author_kind'):
            assert listed_comment.get(field) == viewed_comment.get(field)
        canonical(first['items'][0]['created'])
        canonical(first['items'][0]['updated'])
        original_cursor = first['next_cursor']
        deleted = first['items'][0]
        assert request('/api/collections/comments/records/' + deleted['id'], method='DELETE')[0] == 204
        edited = initial[2]
        assert request('/api/collections/comments/records/' + edited['id'], {'body': 'Edited during scan'}, 'PATCH')[0] == 200
        added = cli('issue', 'comment', targets[0]['key'], '-b', 'Inserted during scan', '--json')
        comments = collect('comment', first)
        assert {r['id'] for r in initial} <= {r['id'] for r in comments}, 'offset shift skipped an existing comment'
        assert next(r for r in comments if r['id'] == edited['id'])['body'] == 'Edited during scan'
        assert (added['id'] in {r['id'] for r in comments}) == (added['id'] > first['items'][-1]['id'])

        initial_claims = truth('claims')
        first_claims = cli('claim', 'list', '--project', 'Alpha', '--limit', '2', '--json')
        assert first_claims['totalItems'] == 3 and first_claims['next_cursor']
        for held in first_claims['items']:
            assert held['member'] == owner['id'] and held['holder'] == owner['name']
            assert held['agent'] == 'bulk-reader-proof' and held['key'].startswith('BULKREAD-')
            canonical(held['claimed'])
            canonical(held['renewed'])
        cli('issue', 'release', first_claims['items'][0]['key'], '--agent', 'bulk-reader-proof')
        cli('issue', 'claim', targets[3]['key'], '--agent', 'bulk-reader-proof')
        claims = collect('claim', first_claims)
        assert {r['id'] for r in initial_claims} <= {r['id'] for r in claims}, 'offset shift skipped an existing claim'

        for noun in ('comment', 'claim'):
            empty = cli(noun, 'list', '--project', 'Empty', '--json')
            assert empty['items'] == [] and empty['totalItems'] == 0 and empty['next_cursor'] == ''
            cli(noun, 'list', '--project', 'missing-project', '--json', code=3)
            for invalid in ('', 'c1_!', '2026-11-06T00:00:00Z'):
                cli(noun, 'list', '--since', invalid, '--json', code=2)
            for limit in ('0', '501', 'not-a-number'):
                cli(noun, 'list', '--limit', limit, '--json', code=2)
            cli(noun, 'list', '--json', token='', code=6)
        cli('comment', 'list', '--project', 'Beta', '--since', original_cursor, '--json', code=2)
        cli('claim', 'list', '--project', 'Alpha', '--since', original_cursor, '--json', code=2)
        cli('comment', 'list', '--project', 'Alpha', '--since', original_cursor, '--json', team='BULKOTHER', code=2)
        assert 'BULKREAD-' in cli('comment', 'list', '--project', 'Alpha')
        assert 'bulk-owner' in cli('claim', 'list', '--project', 'Alpha')

        code, reader = request('/api/collections/members/records', {
            'name': 'bulk-readonly', 'email': 'bulk-readonly@example.invalid', 'kind': 'person',
            'scope': 'teams', 'teams': [targets[0]['team']], 'mode': 'ro',
            'password': 'bulk-reader-password', 'passwordConfirm': 'bulk-reader-password'}, token=admin)
        assert code == 200, ('scoped read-only fixture creation failed', code,
                             {k: v.get('code') for k, v in reader.get('data', {}).items() if isinstance(v, dict)})
        code, auth = request('/api/collections/members/impersonate/' + reader['id'], {'duration': 3600}, token=admin)
        assert code == 200
        reader_token = auth['token']
        for noun in ('comment', 'claim'):
            visible = cli(noun, 'list', '--json', token=reader_token)
            assert visible['items'] and all(r['key'].startswith('BULKREAD-') for r in visible['items'])
            cli(noun, 'list', '--json', token=reader_token, team='BULKOTHER', code=3)
        before_refusal = truth('comments')
        cli('issue', 'comment', targets[0]['key'], '-b', 'Must not save', token=reader_token, code=4)
        assert truth('comments') == before_refusal
        assert request('/api/collections/members/records/' + reader['id'], {'teams': []}, 'PATCH', token=admin)[0] == 200
        cli('comment', 'list', '--project', 'Alpha', '--since', original_cursor, '--json', token=reader_token, code=3)

        # A server lacking the endpoint or required page/record fields must
        # refuse safely, never present an unsupported answer as an empty list.
        class Proxy(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.server.methods.append('POST')
                self.send_error(405)

            def do_GET(self):
                self.server.methods.append('GET')
                self.server.paths.append(self.path)
                selected = self.path.startswith('/api/collections/' + self.server.noun + 's/records')
                if selected and self.server.mode == 'missing':
                    status, data = 404, {'status': 404, 'message': 'Unsupported collection endpoint', 'data': {}}
                else:
                    status, data = request(self.path, token=self.headers.get('Authorization', '').removeprefix('Bearer '))
                    if selected and status == 200:
                        if self.server.mode == 'bad-page':
                            data['perPage'] = 0
                        elif self.server.mode == 'unordered':
                            assert len(data['items']) >= 2
                            data['items'].reverse()
                        elif self.server.mode == 'no-reference':
                            data['items'][0]['expand'].pop('issue', None)
                        elif self.server.mode == 'no-member':
                            data['items'][0].pop('member', None)
                        elif self.server.mode == 'low-total':
                            data['totalItems'], data['totalPages'] = 0, 0
                        elif self.server.mode == 'high-total':
                            data['totalItems'], data['totalPages'] = 999, 2
                        elif self.server.mode == 'capped':
                            data['perPage'] = 500
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(body)

        for noun, mode, expected, hint in [
            ('comment', 'missing', 3, 'Unsupported collection endpoint'),
            ('comment', 'bad-page', 1, 'invalid comment list page'),
            ('comment', 'unordered', 1, 'invalid or unordered comment list record'),
            ('comment', 'no-reference', 1, 'invalid or unordered comment list record'),
            ('claim', 'no-member', 1, 'claim without its member'),
            ('comment', 'low-total', 0, ''),
            ('comment', 'high-total', 0, ''),
            ('comment', 'capped', 1, 'lower --limit'),
            ('comment', 'control', 0, ''),
        ]:
            with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Proxy) as proxy:
                proxy.noun, proxy.mode, proxy.methods, proxy.paths = noun, mode, [], []
                thread = threading.Thread(target=proxy.serve_forever, daemon=True)
                thread.start()
                try:
                    current = dict(env, LLL_URL=f'http://127.0.0.1:{proxy.server_port}')
                    limit = '500' if mode in ('high-total', 'capped') else '2'
                    p = subprocess.run([binary, noun, 'list', '--project', 'Alpha', '--limit', limit, '--json'],
                                       env=current, cwd=root, capture_output=True, text=True, timeout=30)
                    assert p.returncode == expected, (mode, p.returncode, p.stderr)
                    if expected:
                        assert not p.stdout and hint in p.stderr, (mode, p.stdout, p.stderr)
                    else:
                        packet = json.loads(p.stdout)
                        assert packet['perPage'] == int(limit)
                        if mode == 'high-total':
                            assert len(packet['items']) == len(truth('comments'))
                            assert packet['next_cursor'] == '', 'stale count invented another page'
                        else:
                            assert len(packet['items']) == 2
                            assert packet['next_cursor'], 'a low concurrent count ended the scan early'
                        # Same backing database but a different origin: refuse
                        # continuation without accepting an accidental rebind.
                        refused = subprocess.run([binary, noun, 'list', '--project', 'Alpha', '--since', original_cursor, '--json'],
                                                 env=current, cwd=root, capture_output=True, text=True, timeout=30)
                        assert refused.returncode == 2 and not refused.stdout
                        assert 'different list, server, team or project' in refused.stderr
                    assert proxy.methods and set(proxy.methods) == {'GET'}, 'bulk read attempted a write'
                    bulk_requests = [p for p in proxy.paths if p.startswith('/api/collections/' + noun + 's/records')]
                    assert len(bulk_requests) == 1, 'one page needed more than one bulk request'
                    assert not any(p.startswith('/api/collections/issues/records/') for p in proxy.paths), 'N+1 issue metadata reads'
                finally:
                    proxy.shutdown()
                    thread.join(timeout=5)
                    assert not thread.is_alive()
    finally:
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)

print('Bulk reads: comment/claim shapes, keyset inserts/deletes/edits, project/team scope, readonly/narrowed readers, cursor binding and invalid/empty controls passed')
