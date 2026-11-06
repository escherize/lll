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
    code, refused = patch(a, {'state':state})
    assert code == 409 and refused['data']['code'] == 'open_descendants'
    assert fresh(a)['state'] == 'todo'
assert patch(a, {'state':'done','@lll_tree_force_close':True})[0] in (400,409)
assert fresh(a)['state']=='todo'
# Closing must roll back claim deletion if the descendant check refuses.
code, claim = request('/api/lll/issues/' + a['id'] + '/claim', {'agent':'tree-test'})
assert code == 200, (code, claim)
body = {'claim_id':claim['claim_id'], 'agent':'tree-test'}
code, refused = request('/api/lll/issues/' + a['id'] + '/close', body)
assert code == 409 and refused['data']['code'] == 'open_descendants'
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
# Traverse the full tree before applying state/search filters or pagination.
filtered_root = json.loads(cli('issue','create','-t','Filter root','--json').stdout)
fk = f"TREEA-{filtered_root['number']}"
intermediate = json.loads(cli('issue','create','-t','Closed intermediate','--state','done','--parent',fk,'--json').stdout)
ik = f"TREEA-{intermediate['number']}"
leaf = json.loads(cli('issue','create','-t','Needle deep leaf','--parent',ik,'--json').stdout)
sibling = json.loads(cli('issue','create','-t','Sibling leaf','--parent',fk,'--json').stdout)
cli('issue','create','-t','Needle outside the subtree')
direct = json.loads(cli('issue','list','--parent',fk,'--json').stdout)
assert {r['id'] for r in direct['items']}=={intermediate['id'],sibling['id']}
whole = json.loads(cli('issue','list','--under',fk,'--sort','created','--json').stdout)
assert {r['id'] for r in whole['items']}=={filtered_root['id'],intermediate['id'],leaf['id'],sibling['id']}
assert whole['totalItems']==4
by_id = {r['id']:r for r in whole['items']}
assert by_id[filtered_root['id']]['children_summary']=={'done':1,'total':2}
assert by_id[intermediate['id']]['children_summary']=={'done':0,'total':1}
assert by_id[leaf['id']]['children_summary']=={'done':0,'total':0}
assert by_id[leaf['id']]['parent_ref']['key']==ik
view = json.loads(cli('issue','view',fk,'--json').stdout)
assert view['children_summary']=={'done':1,'total':2}
assert {r['id'] for r in view['children_refs']}=={intermediate['id'],sibling['id']}
assert view['parent_ref'] is None
for mode in ((),('--raw',)):
    text = cli('issue','view',fk,*mode).stdout
    assert '1/2 done' in text and ik in text
    text = cli('issue','view',f"TREEA-{leaf['number']}",*mode).stdout
    assert 'Parent:' in text and ik in text
page = json.loads(cli('issue','list','--under',fk,'--sort','created','--limit','1','--page','2','--json').stdout)
assert page['totalItems']==4 and page['items'][0]['id']==whole['items'][1]['id']
needle = json.loads(cli('issue','list','--under',fk,'--search','Needle','--state','todo','--json').stdout)
assert [r['id'] for r in needle['items']]==[leaf['id']]
roots = json.loads(cli('issue','list','--parent','none','--json').stdout)
assert all(r['parent']=='' for r in roots['items'])
assert cli('issue','list','--parent',fk,'--under',fk,success=False).returncode==2
assert cli('issue','list','--under','',success=False).returncode==2
# Explicit --force is required even with piped input; there is no implicit
# confirmation or cascade, and a refused close keeps the parent open.
close_refused = cli('issue','close',fk,success=False)
assert close_refused.returncode==4 and f"lll issue close {fk} --force" in close_refused.stderr
assert fresh(filtered_root)['state']=='todo'
cli('issue','close',fk,'--force')
assert fresh(filtered_root)['state']=='done' and fresh(leaf)['state']=='todo'
cli('issue','update',fk,'--state','todo')
state_refused = cli('issue','update',fk,'--state','cancelled',success=False)
assert state_refused.returncode==4 and f"--state cancelled --force" in state_refused.stderr
cli('issue','update',fk,'--state','cancelled','--force')
assert fresh(filtered_root)['state']=='cancelled' and fresh(leaf)['state']=='todo'
cli('issue','update',fk,'--state','todo')
cli('issue','claim',fk,'--agent','tree-close')
held = json.loads(cli('issue','view',fk,'--json').stdout)['claim']['id']
combined_refused = cli('issue','update',fk,'--state','done','--assignee',who['name'],'--agent','tree-close',success=False)
assert combined_refused.returncode==4 and fresh(filtered_root)['state']=='todo'
assert json.loads(cli('issue','view',fk,'--json').stdout)['claim']['id']==held
cli('issue','update',fk,'--state','done','--assignee',who['name'],'--agent','tree-close','--force')
assert json.loads(cli('issue','view',fk,'--json').stdout)['claim'] is None
assert fresh(filtered_root)['state']=='done' and fresh(leaf)['state']=='todo'
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
        ('issue','list','--parent',root_key),
        ('issue','list','--under',root_key),
        ('issue','list','--parent','none'),
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
