#!/usr/bin/env python3
"""The agenda stays in its selected team and counts every dependent page."""
import base64
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.parse

binary = str(Path(sys.argv[1]).resolve())
alpha = {'id': 'teamalpha000001', 'key': 'ALPHA', 'name': 'Alpha'}
beta = {'id': 'teambeta0000001', 'key': 'BETA', 'name': 'Beta'}
actor = {'id': 'agendamember001', 'name': 'fixture-worker'}


def issue(team, number, priority=3, blocked=None):
    return {'id': f'{team["key"].lower()}{number:010}', 'team': team['id'],
            'number': number, 'title': f'{team["key"]} work {number}',
            'priority': priority, 'state': 'todo', 'assignee': '',
            'blocked_by': blocked or [], 'created': '2026-09-01 00:00:00.000Z',
            'expand': {'team': team}}


class API(http.server.BaseHTTPRequestHandler):
    rows = [issue(alpha, 1), issue(beta, 1, 1)]
    calls = []
    claims = []
    deny_claim = False
    fail_kind = ''

    def answer(self, body, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if '/members/records/' in parsed.path:
            return self.answer(actor)
        page = int(q.get('page', ['1'])[0])
        limit = int(q.get('perPage', ['30'])[0])
        f = q.get('filter', [''])[0]
        self.calls.append((parsed.path, page, q))
        if '/teams/records' in parsed.path:
            rows = [t for t in (alpha, beta) if t['key'] in f]
        else:
            kind = 'dependents' if q.get('fields') == ['id,blocked_by'] else 'candidates'
            if self.fail_kind == kind and page == 2:
                return self.answer({'message': 'fixture later page refused'}, 500)
            rows = [r for r in self.rows if
                    ("team='" + alpha['id'] + "'" not in f or r['team'] == alpha['id']) and
                    ("team='" + beta['id'] + "'" not in f or r['team'] == beta['id'])]
        self.answer({'items': rows[(page - 1) * limit:page * limit],
                     'totalItems': len(rows), 'totalPages': (len(rows) + limit - 1) // limit})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.claims.append((self.path, body))
        if self.deny_claim:
            return self.answer({'message': 'issue is already claimed by another worker'}, 400)
        self.answer({'claim_id': 'fixtureclaim001', 'member_id': actor['id'],
                     'member_name': actor['name'], 'already_owned': False})

    def log_message(self, *_):
        pass


with tempfile.TemporaryDirectory(prefix='lll-agenda-scope-') as directory:
    root = Path(directory)
    cwd = root / 'work'
    cwd.mkdir()
    home_config = root / 'config/lll/lll.toml'
    home_config.parent.mkdir(parents=True)
    repo_config = cwd / '.lll.toml'
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), API)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    payload = base64.urlsafe_b64encode(json.dumps({'id': actor['id'], 'exp': 4102444800}).encode()).decode().rstrip('=')
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
    env.update(HOME=directory, LLL_CONFIG_HOME=str(root / 'config'),
               LLL_URL=f'http://127.0.0.1:{server.server_port}',
               LLL_TOKEN='fake.' + payload + '.fixture')

    def run(*args, selected=None):
        child = dict(env)
        if selected:
            child['LLL_TEAM'] = selected
        return subprocess.run([binary, 'issue', 'next', *args], cwd=cwd, env=child,
                              text=True, capture_output=True, timeout=15)

    def chosen(result, key):
        assert result.returncode == 0 and result.stdout.strip() == key, result

    try:
        home_config.write_text('team = "ALPHA"\n')
        chosen(run(), 'ALPHA-1')
        home_config.write_text('team = "BETA"\n')
        repo_config.write_text('team = "ALPHA"\n')
        chosen(run(), 'ALPHA-1')
        chosen(run(selected='BETA'), 'BETA-1')
        chosen(run('--team', 'ALPHA', selected='BETA'), 'ALPHA-1')
        assert repo_config.read_text() == 'team = "ALPHA"\n'
        assert home_config.read_text() == 'team = "BETA"\n'
        value = run('--json')
        assert value.returncode == 0 and json.loads(value.stdout)['team'] == alpha['id'], value
        chosen(run('--claim'), 'ALPHA-1')
        assert API.claims == [('/api/lll/issues/alpha0000000001/claim', {'member': actor['id']})], API.claims
        API.deny_claim = True
        refused = run('--claim')
        assert refused.returncode != 0 and not refused.stdout and 'already claimed' in refused.stderr, refused
        API.deny_claim = False
        API.rows = [issue(beta, 1, 1)]
        empty = run()
        assert empty.returncode != 0 and not empty.stdout and 'agenda is empty' in empty.stderr, empty
        API.rows = [issue(alpha, 1), issue(beta, 1, 1)]
        repo_config.unlink()
        home_config.unlink()
        chosen(run(), 'BETA-1')
        # The first candidate frees one issue on page one; the second frees
        # two only on page two. Foreign-team dependents must not affect ALPHA.
        a1, a2 = issue(alpha, 1), issue(alpha, 2)
        dependencies = [issue(alpha, i + 3, blocked=[a1['id']] if i == 0 else ['missingblock001'])
                        for i in range(498)]
        dependencies += [issue(alpha, 501, blocked=[a2['id']]),
                         issue(alpha, 502, blocked=[a2['id']])]
        API.rows = [a1, a2, *dependencies,
                    *[issue(beta, i + 2, blocked=[a1['id']]) for i in range(20)]]
        API.calls = []
        chosen(run(selected='ALPHA'), 'ALPHA-2')
        pages = [(p, q) for path, p, q in API.calls if q.get('fields') == ['id,blocked_by']]
        assert [p for p, _ in pages] == [1, 2], pages
        for _, q in pages:
            assert q['sort'] == ['created,id'] and alpha['id'] in q['filter'][0], q
        for kind in ('candidates', 'dependents'):
            API.fail_kind = kind
            failed = run(selected='ALPHA')
            assert failed.returncode != 0 and not failed.stdout, failed
            assert 'fixture later page refused' in failed.stderr, failed
            API.fail_kind = ''
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
print('Agenda: home/repo/env/explicit scope, JSON, claim ordering/refusal, empty/unscoped agenda, complete scoped dependent counts and later-page failures passed')
