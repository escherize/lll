#!/usr/bin/env python3
"""A successful create remains successful when subsequent detail reads fail."""
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
posts = []
detail_reads = []


class Proxy(http.server.BaseHTTPRequestHandler):
    def forward(self):
        path = urllib.parse.urlsplit(self.path)
        if self.command == 'GET' and path.path.startswith('/api/collections/issues/records/'):
            detail_reads.append(self.path)
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"message":"detail reads unavailable"}')
            return
        data = None
        if self.command == 'POST':
            posts.append(self.path)
            data = self.rfile.read(int(self.headers['Content-Length']))
        request = urllib.request.Request(api + self.path, method=self.command, data=data,
            headers={'Authorization': self.headers.get('Authorization', ''),
                     'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            self.send_response(response.status)
            self.end_headers()
            self.wfile.write(body)

    do_GET = forward
    do_POST = forward

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    result = subprocess.run([binary, 'issue', 'create', 'Create response regression', '--json'],
        env=dict(os.environ, LLL_URL=f'http://127.0.0.1:{server.server_port}', LLL_TEAM='ENG'),
        capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record['id'] and record['number'] > 0, record
    assert record['title'] == 'Create response regression', record
    assert record['expand']['team']['key'] == 'ENG', record
    assert len(posts) == 1, posts
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(posts[0]).query)['expand'] == [
        'team,assignee,labels,project'], posts
    assert not detail_reads, detail_reads
    request = urllib.request.Request(api + '/api/collections/issues/records/' + record['id'],
        headers={'Authorization': 'Bearer ' + os.environ['LLL_TOKEN']})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert json.load(response)['title'] == record['title']
finally:
    server.shutdown()
    server.server_close()
    thread.join()
print('create --json: committed record and expanded response survive unavailable detail reads')
