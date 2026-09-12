#!/usr/bin/env python3
"""Exercise complete document context against the suite's isolated server."""
import concurrent.futures
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='PAGE')


def cli(*args, url=api):
    return subprocess.check_output([binary, *args], env=dict(env, LLL_URL=url), text=True, timeout=30)


def post(collection, record):
    request = urllib.request.Request(api + '/api/collections/' + collection + '/records',
        data=json.dumps(record).encode(), headers={'Authorization': 'Bearer ' + env['LLL_TOKEN'],
                                                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


team = post('teams', {'key': 'PAGE', 'name': 'Pagination fixture'})
issue = post('issues', {'team': team['id'], 'title': 'Complete context', 'state': 'todo'})
key = f'PAGE-{issue["number"]}'
expected = [f'page-{i:04d}' for i in range(501)]


def create(i):
    return post('docs', {'team': team['id'], 'slug': expected[i], 'kind': 'finding',
        'title': f'Page finding {i}', 'body': f'Pagination evidence {i}',
        'paths': 'pagination/last' if i == 500 else 'pagination/earlier',
        'issues': [issue['id']]})


with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    records = list(pool.map(create, range(501)))
docs = json.loads(cli('doc', 'list', '--json'))['items']
assert [doc['slug'] for doc in docs] == expected
findings = json.loads(cli('finding', 'list', '--json'))
assert [doc['slug'] for doc in findings] == expected
context = json.loads(cli('issue', 'view', key, '--json'))
for field in ['docs', 'findings']:
    assert [doc['slug'] for doc in context[field]] == expected, field
    assert context[field][-1]['body'] == 'Pagination evidence 500', field
assert 'page-0500' in cli('finding', 'near', 'pagination/last')
assert 'page-0500' in cli('search', 'Pagination evidence 500', '--docs')

# A later page failure must not look like a successfully truncated list.
pages = []


class FailingPage(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == '/api/collections/docs/records':
            page = int(urllib.parse.parse_qs(parsed.query).get('page', ['1'])[0])
            pages.append(page)
            if page == 2:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'{"message":"second page unavailable"}')
                return
        request = urllib.request.Request(api + self.path,
            headers={'Authorization': self.headers.get('Authorization', '')})
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.send_response(response.status)
            self.end_headers()
            self.wfile.write(response.read())

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FailingPage)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    for args in [('doc', 'list', '--json'), ('issue', 'view', key, '--json')]:
        pages.clear()
        result = subprocess.run([binary, *args],
            env=dict(env, LLL_URL=f'http://127.0.0.1:{server.server_port}'),
            text=True, capture_output=True, timeout=15)
        assert result.returncode != 0 and not result.stdout, result
        assert pages == [1, 2], pages
        assert 'second page unavailable' in result.stderr, result.stderr
finally:
    server.shutdown()
    server.server_close()
    thread.join()
print('Document pagination: 501 scoped docs/findings/links, last-page retrieval and failure propagation passed')
