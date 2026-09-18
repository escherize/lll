#!/usr/bin/env python3
"""Complete collection lists, scoped pages, failures and export member names."""
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
team = {'id': 'scopeteam000001', 'key': 'SCOPE', 'name': 'Scoped fixture'}


class API(http.server.BaseHTTPRequestHandler):
    size = 201
    fail = None
    archived = False
    calls = []
    export = False

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        collection = parsed.path.split('/')[3]
        page = int(query.get('page', ['1'])[0])
        limit = int(query.get('perPage', ['30'])[0])
        type(self).calls.append((collection, page, query))
        if collection == self.fail and page == 2:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"message":"fixture page two refused"}')
            return
        if self.fail == 'decode' and page == 2:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{malformed page two')
            return
        if collection == 'teams' and query.get('filter'):
            rows = [team]
        elif collection in ('docs', 'comments'):
            rows = []
        elif collection == 'issues':
            rows = ([{'id': 'exportissue0001', 'team': team['id'], 'number': 1,
                      'title': 'Late member names', 'state': 'todo', 'priority': 2,
                      'assignee': '000000000000200', 'creator': '000000000000200',
                      'description': 'Export must retain the name after page one.',
                      'expand': {'team': team}}]
                    if self.export else [])
        else:
            rows = [dict(id=f'{i:015}', name=f'item-{i:03}',
                         email=f'item-{i:03}@example.invalid', key=f'T{i:03}',
                         archived=self.archived and i == self.size - 1,
                         kind='person', status='planned', color='#123456',
                         team=team['id'], expand={'team': team})
                    for i in range(self.size)]
        count = len(rows)
        body = json.dumps({'items': rows[(page - 1) * limit:page * limit],
                           'totalItems': count, 'totalPages': (count + limit - 1) // limit,
                           'page': page, 'perPage': limit}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


with tempfile.TemporaryDirectory(prefix='lll-collection-pages-') as directory:
    root = Path(directory)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), API)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
    env.update(HOME=directory, LLL_CONFIG_HOME=str(root / 'config'),
               LLL_URL=f'http://127.0.0.1:{server.server_port}',
               LLL_TOKEN='fake-collection-pagination-token')

    def run(*args, scoped=False):
        scoped_env = dict(env)
        if scoped:
            scoped_env['LLL_TEAM'] = 'SCOPE'
        return subprocess.run([binary, *args], cwd=root, env=scoped_env,
                              text=True, capture_output=True, timeout=15)

    try:
        nouns = [('member', 'members'), ('team', 'teams'),
                 ('project', 'projects'), ('label', 'labels')]
        for size in (0, 200, 201, 400):
            API.size = size
            for noun, collection in nouns:
                API.calls = []
                result = run(noun, 'list', '--json')
                assert result.returncode == 0, result.stderr
                response = json.loads(result.stdout)
                assert set(response) == {'items'}, response.keys()
                rows = response['items'] or []
                assert len(rows) == size, (noun, size, len(rows))
                assert [r['id'] for r in rows] == [f'{i:015}' for i in range(size)]
                pages = [p for c, p, _ in API.calls if c == collection]
                assert pages == list(range(1, max(1, (size + 199) // 200) + 1)), pages
        API.size = 201
        for noun, collection in nouns:
            API.fail = collection
            result = run(noun, 'list', '--json')
            assert result.returncode != 0 and not result.stdout, (noun, result)
            assert 'fixture page two refused' in result.stderr, result.stderr
            API.fail = 'decode'
            result = run(noun, 'list', '--json')
            assert result.returncode != 0 and not result.stdout, (noun, result)
            assert 'decoding' in result.stderr, result.stderr
            API.fail = None
        for noun, collection in [('project', 'projects'), ('label', 'labels')]:
            API.calls = []
            result = run(noun, 'list', '--json', scoped=True)
            assert result.returncode == 0, result.stderr
            assert len(json.loads(result.stdout)['items']) == 201
            pages = [q for c, _, q in API.calls if c == collection]
            assert len(pages) == 2
            for query in pages:
                assert query['filter'] == ["team='" + team['id'] + "'"], query
                assert query['expand'] == ['team'] and query['sort'] == ['name,id'], query
        API.archived = True
        normal = run('team', 'list', '--json')
        all_teams = run('team', 'list', '--json', '--archived')
        assert normal.returncode == all_teams.returncode == 0
        assert len(json.loads(normal.stdout)['items']) == 200
        assert len(json.loads(all_teams.stdout)['items']) == 201
        assert json.loads(all_teams.stdout)['items'][-1]['archived']
        API.archived = False
        API.export = True
        API.calls = []
        result = run('export', str(root / 'mirror'), scoped=True)
        assert result.returncode == 0, result.stderr
        mirror = (root / 'mirror/issues/SCOPE-1.md').read_text()
        assert '\nassignee: item-200\n' in mirror, mirror
        assert '\ncreator: item-200\n' in mirror, mirror
        assert [p for c, p, _ in API.calls if c == 'members'] == [1, 2]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
print('Collection pagination: complete/boundary/empty lists, scoped pages, late HTTP/decode failures, archives and export names passed')
