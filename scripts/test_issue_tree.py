#!/usr/bin/env python3
"""LLL-177: tree invariants through native HTTP and the atomic close route."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
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
print('Issue trees: native cycles/cross-team refs refused; descendant close preserves claims on refusal; force preserves children; reparent/delete preserve the subtree; reciprocal HTTP updates cannot form a cycle')
