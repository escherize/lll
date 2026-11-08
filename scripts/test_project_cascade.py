#!/usr/bin/env python3
"""Guarded project teardown against an isolated real board."""
import json
import http.server
import threading
import urllib.request
import urllib.error
import os
import subprocess
import sys
import tempfile
import urllib.parse

binary, api = sys.argv[1:]
assert urllib.parse.urlsplit(api).hostname == '127.0.0.1'
with tempfile.TemporaryDirectory(prefix='lll-cascade-cli-') as home:
    env = dict(os.environ, LLL_URL=api, LLL_TEAM='CASCADE', LLL_CONFIG_HOME=home)
    def cli(*args, expected=0):
        result = subprocess.run([binary, *args], env=env, capture_output=True, text=True, timeout=40)
        assert result.returncode == expected, f'{args[:3]}: exit {result.returncode}, expected {expected}: {result.stderr}'
        if expected:
            assert not result.stdout
        return result
    def packet(*args):
        return json.loads(cli(*args).stdout)
    cli('team','create','--key','CASCADE','-n','Cascade fixture')
    cli('project','create','Tear down')
    issue = packet('issue','create','-t','Preserve until confirmed','--project','Tear down','--json')
    comment = packet('issue','comment',issue['key'],'-b','Keep until cascade','--json')
    preview = packet('project','delete','Tear down','--cascade','--dry-run','--json')
    assert preview['issues'][0]['id'] == issue['id'] and preview['blockers'] == []
    # A read-only preview leaves the entire current issue and comment unchanged.
    before = packet('issue','view',issue['key'],'--json')
    assert packet('project','delete','Tear down','--cascade','--dry-run','--json') == preview
    assert packet('issue','view',issue['key'],'--json') == before
    cli('issue','comment',issue['key'],'-b','New information after preview')
    cli('project','delete','Tear down','--cascade','--if-preview',preview['revision'],'--json','--yes',expected=4)
    assert packet('issue','view',issue['key'],'--json')['description'] == before['description']
    # A successful HTTP status with incomplete or contradictory preview data
    # cannot authorize a delete. Forward discovery/resolution to the real board.
    class BrokenPreview(http.server.BaseHTTPRequestHandler):
        value = None
        writes = 0
        def do_GET(self):
            if self.path.endswith('/cascade'):
                raw = json.dumps(type(self).value).encode()
                self.send_response(200)
            else:
                req = urllib.request.Request(api + self.path, headers={'Authorization': self.headers.get('Authorization', '')})
                try:
                    response = urllib.request.urlopen(req, timeout=20)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    raw = response.read()
                    self.send_response(response.status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(raw)
        def do_POST(self):
            type(self).writes += 1
            self.send_error(500)
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), BrokenPreview)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env['LLL_URL'] = f'http://127.0.0.1:{server.server_port}'
        for bad in [dict(preview, issues=None), {k:v for k,v in preview.items() if k != 'issues'},
                    dict(preview, blockers=None), dict(preview, project='different'),
                    dict(preview, issues=[preview['issues'][0], preview['issues'][0]])]:
            BrokenPreview.value = bad
            cli('project','delete','Tear down','--cascade','--json','--yes',expected=1)
        assert BrokenPreview.writes == 0
    finally:
        env['LLL_URL'] = api
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    cli('issue','claim',issue['key'])
    held = packet('project','delete','Tear down','--cascade','--dry-run','--json')
    assert any(b['kind'] == 'claims.issue' for b in held['blockers'])
    cli('project','delete','Tear down','--cascade','--json','--yes',expected=4)
    cli('issue','release',issue['key'])
    current = packet('project','delete','Tear down','--cascade','--dry-run','--json')
    removed = packet('project','delete','Tear down','--cascade','--if-preview',current['revision'],'--json','--yes')
    assert removed['deleted'] and removed['project'] == preview['project'] and removed['issues'][0]['id'] == issue['id']
    cli('issue','view',issue['key'],expected=3)
    cli('project','view','Tear down',expected=3)
    # Existing --force remains detachment, not issue deletion.
    cli('project','create','Detach only')
    kept = packet('issue','create','-t','Keep this card','--project','Detach only','--json')
    cli('project','delete','Detach only','--force','--yes')
    assert not packet('issue','view',kept['key'],'--json')['project']
    cli('project','delete','missing','--dry-run',expected=2)
    cli('project','delete','missing','--cascade','--force',expected=2)
print('Project cascade: read-only stable preview, stale-comment guard, claims refusal, revision-bound deletion and unchanged force-detach passed')
