#!/usr/bin/env python3
"""LLL-177: tree invariants through native HTTP and the atomic close route."""
from concurrent.futures import ThreadPoolExecutor
import json
import http.server
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
assert urllib.parse.urlsplit(api).hostname == '127.0.0.1', 'requires an isolated loopback board'
token = os.environ['LLL_TOKEN']


def request(path, body=None, method=None):
    req = urllib.request.Request(api + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json', 'Authorization':'Bearer ' + token})
    try:
        response = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else None


def create(collection, body):
    code, result = request('/api/collections/' + collection + '/records', body)
    assert code == 200, (code, result)
    return result


def issue(title, parent='', team=None, state='todo'):
    return create('issues', {'team':(team or alpha)['id'], 'title':title, 'parent':parent, 'state':state})


def patch(record, body, suffix=''):
    return request('/api/collections/issues/records/' + record['id'] + suffix, body, 'PATCH')


def fresh(record):
    code, result = request('/api/collections/issues/records/' + record['id'])
    assert code == 200
    return result


alpha = create('teams', {'key':'TREEA', 'name':'Tree A'})
beta = create('teams', {'key':'TREEB', 'name':'Tree B'})
a = issue('Root')
b = issue('Closed child', a['id'], state='done')
c = issue('Open grandchild', b['id'])
other = issue('Other team', team=beta)
assert patch(a, {'parent':c['id']})[0] == 400
assert patch(a, {'parent':a['id']})[0] == 400
assert patch(b, {'parent':other['id']})[0] == 400
assert fresh(a)['parent'] == '' and fresh(b)['parent'] == a['id']
for state in ('done', 'cancelled'):
    assert patch(a, {'state':state})[0] == 400
    assert fresh(a)['state'] == 'todo'
# Closing must roll back claim deletion if the descendant check refuses.
code, claim = request('/api/lll/issues/' + a['id'] + '/claim', {'agent':'tree-test'})
assert code == 200, (code, claim)
body = {'claim_id':claim['claim_id'], 'agent':'tree-test'}
assert request('/api/lll/issues/' + a['id'] + '/close', body)[0] == 400
claims = request('/api/collections/claims/records?filter=' + urllib.parse.quote('issue="' + a['id'] + '"'))[1]['items']
assert len(claims) == 1 and claims[0]['id'] == claim['claim_id']
assert request('/api/lll/issues/' + a['id'] + '/close', dict(body, force=True))[0] == 200
assert fresh(a)['state'] == 'done' and fresh(c)['state'] == 'todo'
# Native writers also need explicit force, without forcing a child's state.
assert patch(b, {'state':'todo'})[0] == 200
assert patch(b, {'state':'cancelled'}, '?force=true')[0] == 200
assert fresh(c)['state'] == 'todo'
# Reparent the subtree; deleting the new parent detaches only its direct child.
d = issue('New root')
assert patch(b, {'parent':d['id']})[0] == 200
assert fresh(c)['parent'] == b['id']
assert request('/api/collections/issues/records/' + d['id'], method='DELETE')[0] == 204
assert fresh(b)['parent'] == '' and fresh(c)['parent'] == b['id']
# Both reciprocal edits start from valid roots. At most one may commit.
x, y = issue('Concurrent A'), issue('Concurrent B')
start = threading.Barrier(2)
def attach(pair):
    child, parent = pair
    start.wait(timeout=5)
    return patch(child, {'parent':parent['id']})[0]
with ThreadPoolExecutor(max_workers=2) as pool:
    codes = list(pool.map(attach, ((x,y), (y,x))))
assert sorted(codes) == [200,400], codes
# The user's CLI paths use the same relation and composite write boundary.
def cli(*args, success=True):
    result = subprocess.run([binary,*args], env=dict(os.environ,LLL_URL=api,LLL_TEAM='TREEA'),
                            capture_output=True,text=True,timeout=30)
    assert (result.returncode==0)==success,(result.args,result.returncode,result.stdout,result.stderr)
    return result

root = json.loads(cli('issue','create','-t','CLI root','--parent','none','--json').stdout)
root_key = f"TREEA-{root['number']}"
child = json.loads(cli('issue','create','-t','CLI child','--parent',root_key,'--json').stdout)
child_key = f"TREEA-{child['number']}"
assert child['parent']==root['id']
cleared = json.loads(cli('issue','update',child_key,'--parent','none','--json').stdout)
assert cleared['parent']==''
who = json.loads(cli('whoami','--json').stdout)
combined = json.loads(cli('issue','update',child_key,'--parent',root_key,'--assignee',who['name'],'--json').stdout)
assert combined['parent']==root['id'] and combined['assignee']
cleared = json.loads(cli('issue','update',child_key,'--parent','none','--assignee','none','--json').stdout)
assert cleared['parent']=='' and cleared['assignee']==''
refused = cli('issue','update',child_key,'--parent',f"TREEB-{other['number']}",'--title','Must not land',success=False)
assert refused.returncode==4 and fresh(child)['title']=='CLI child'
assert cli('issue','update',root_key,'--parent',root_key,success=False).returncode==4
assert cli('issue','update',child_key,'--parent','',success=False).returncode==2
# Equal version strings do not authorize a parent write. No POST/PATCH is
# allowed through this proxy, even when all ordinary record reads succeed.
class NoParents(http.server.BaseHTTPRequestHandler):
    writes = 0
    def do_GET(self):
        if self.path == '/.well-known/lll':
            data = json.dumps({'service':'lll','version':'1.4.1','capabilities':['issues.idempotency']}).encode()
        else:
            upstream = urllib.request.Request(api+self.path,headers={'Authorization':self.headers.get('Authorization','')})
            with urllib.request.urlopen(upstream,timeout=15) as response:
                data = response.read()
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        type(self).writes += 1
        self.send_error(500,'unexpected write')
    do_PATCH = do_POST
    def log_message(self,*args):
        pass

proxy = http.server.ThreadingHTTPServer(('127.0.0.1',0),NoParents)
proxy.daemon_threads = True
thread = threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
try:
    for args in (
        ('issue','create','-t','Unsupported parent','--parent',root_key),
        ('issue','create','-t','Unsupported keyed parent','--parent',root_key,'--idempotency-key','parent-intent'),
        ('issue','create','-t','Unsupported explicit root','--parent','none'),
        ('issue','update',child_key,'--parent',root_key),
        ('issue','update',child_key,'--parent','none'),
    ):
        refused = subprocess.run([binary,*args],capture_output=True,text=True,timeout=30,
            env=dict(os.environ,LLL_URL=f'http://127.0.0.1:{proxy.server_port}',LLL_TEAM='TREEA'))
        assert refused.returncode!=0 and 'does not support issue parents' in refused.stderr,refused.stderr
    assert NoParents.writes==0,NoParents.writes
finally:
    proxy.shutdown();proxy.server_close();thread.join(timeout=5)
print('Issue trees: native cycles/cross-team refs refused; descendant close preserves claims on refusal; force preserves children; reparent/delete preserve the subtree; reciprocal HTTP updates cannot form a cycle')
