#!/usr/bin/env python3
"""LLL-609: every issue, comment and claim write leaves an audit row, read by cursor."""
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
assert urllib.parse.urlsplit(api).hostname == '127.0.0.1', 'requires an isolated loopback board'
su = os.environ['LLL_TEST_SUPERUSER_TOKEN']
env = dict(os.environ, LLL_URL=api, LLL_TEAM='AUDT', LLL_AGENT='audit-a')


def call(path, payload=None, *, method=None, token=None):
    headers = {'Authorization': 'Bearer ' + (env['LLL_TOKEN'] if token is None else token)}
    data = None if payload is None else json.dumps(payload).encode()
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(api + path, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        body = response.read()
        return response.status, (json.loads(body) if body else None)


def cli(*args, code=0, **extra):
    result = subprocess.run([binary, *args], env=dict(env, **extra), text=True, capture_output=True, timeout=30)
    assert result.returncode == code, (result.args, result.returncode, result.stdout, result.stderr)
    return result


def activity(*args):
    return json.loads(cli('activity', '--json', *args).stdout)['items']


def subsequence(rows, wanted):
    """Each (collection, action, field) of wanted appears in rows, in order."""
    at = 0
    for collection, action, field in wanted:
        while at < len(rows) and not (rows[at]['collection'] == collection and rows[at]['action'] == action
                                      and (field is None or field in rows[at]['changes'])):
            at += 1
        assert at < len(rows), (collection, action, field, [(r['collection'], r['action'], sorted(r['changes'])) for r in rows])
        at += 1


me = json.loads(cli('whoami', '--json').stdout)
me_id = me.get('id') or me.get('member', {}).get('id')
assert me_id, me
cli('team', 'create', '--key', 'AUDT', '-n', 'Audited')
cli('team', 'create', '--key', 'AUDO', '-n', 'Other team')
cli('project', 'create', 'Audited work')

# The lifecycle an agent drives: create, comment, claim, start, close.
cli('issue', 'create', '-t', 'Audited issue')
cli('issue', 'comment', 'AUDT-1', '-b', 'first look at the audit log')
cli('issue', 'claim', 'AUDT-1')
cli('issue', 'update', 'AUDT-1', '--state', 'in-progress')
cli('issue', 'close', 'AUDT-1')

rows = activity()
subsequence(rows, [
    ('issues', 'create', 'title'),
    ('comments', 'create', 'body'),
    ('claims', 'create', 'member'),
    ('issues', 'update', 'state'),
    ('claims', 'delete', 'member'),
    ('issues', 'update', 'state'),
])
seqs = [r['seq'] for r in rows]
assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), seqs
team_id = rows[0]['team']
host = socket.gethostname()
for r in rows:
    assert r['team'] == team_id and r['number'] == 1, r
    assert (r['actor'], r['actor_kind'], r['agent'], r['origin_host']) == (me_id, 'person', 'audit-a', host), r
comment = next(r for r in rows if r['collection'] == 'comments')
assert comment['changes']['body'] == {'from': None, 'to': 'first look at the audit log'}, comment
started = next(r for r in rows if r['collection'] == 'issues' and r['changes'].get('state', {}).get('to') == 'in-progress')
assert started['changes']['state']['from'] == 'todo', started

# Plain output: one line per event and the cursor on stderr, off the data channel.
plain = cli('activity')
lines = plain.stdout.splitlines()
assert len(lines) == len(rows), plain.stdout
assert all('\tAUDT-1\t' in line for line in lines), plain.stdout
assert any(line.endswith('\tclaimed') for line in lines), plain.stdout
assert any('\tcommented: first look at the audit log' in line for line in lines), plain.stdout
assert any('state todo -> in-progress' in line for line in lines), plain.stdout
cursor = rows[-1]['seq']
assert f'cursor {cursor}: lll activity --since {cursor}' in plain.stderr, plain.stderr

# The cursor: nothing after it until something happens, then exactly that.
quiet = cli('activity', '--since', str(cursor))
assert quiet.stdout == '' and f'no activity after {cursor}' in quiet.stderr, quiet
cli('issue', 'comment', 'AUDT-1', '-b', 'second look')
after = activity('--since', str(cursor))
assert [(r['collection'], r['action']) for r in after] == [('comments', 'create')], after

# --limit pages; the last item's seq continues the read without a gap.
first, rest = activity('--limit', '2'), activity('--since', str(activity('--limit', '2')[-1]['seq']))
assert [r['seq'] for r in first + rest] == [r['seq'] for r in activity()]
cli('activity', '--limit', '0', code=2)
cli('activity', '--since', 'x', code=2)

# --project: only events on that project's issues.
cli('issue', 'create', '-t', 'In the project', '--project', 'Audited work')
in_project = activity('--project', 'Audited work')
assert in_project and {r['number'] for r in in_project} == {2}, in_project

# A superuser write is attributed to the superuser, not to a member.
issue1 = json.loads(cli('issue', 'view', 'AUDT-1', '--json').stdout)
status, _ = call(f"/api/collections/issues/records/{issue1['id']}", {'title': 'Renamed by an admin'}, method='PATCH', token=su)
assert status == 200
renamed = activity()[-1]
assert (renamed['actor_kind'], renamed['actor'], renamed['changes']['title']['to']) == ('superuser', '', 'Renamed by an admin'), renamed


def member(name, teams):
    status, rec = call('/api/collections/members/records', {
        'name': name, 'email': f'{name}@audit.invalid', 'password': 'audit-pass-123', 'passwordConfirm': 'audit-pass-123',
        'kind': 'person', 'scope': 'teams', 'teams': teams, 'mode': 'rw'}, token=su)
    assert status == 200, rec
    status, tok = call(f"/api/collections/members/impersonate/{rec['id']}", {'duration': 3600}, token=su)
    assert status == 200, tok
    return tok['token']


# Scope: rows are read under the issues rule.
status, other = call('/api/collections/teams/records?filter=' + urllib.parse.quote("key='AUDO'"))
other_id = other['items'][0]['id']
outsider, insider = member('audit-outsider', [other_id]), member('audit-insider', [team_id])
path = '/api/collections/audit_events/records?perPage=500&filter=' + urllib.parse.quote(f"team='{team_id}'")
assert call(path, token=outsider)[1]['totalItems'] == 0
assert call(path, token=insider)[1]['totalItems'] == len(activity())
anonymous = call(path, token='')
assert anonymous[0] in (401, 403) or anonymous[1]['totalItems'] == 0, anonymous

# Append-only: no member and no superuser writes a row through the API;
# retention is a superuser delete.
row = activity()[0]
row_path = f"/api/collections/audit_events/records/{row['id']}"
assert call('/api/collections/audit_events/records', {'seq': 99999, 'collection': 'issues', 'record': 'x',
                                                     'action': 'create', 'actor_kind': 'system'}, token=su)[0] == 403
assert call(row_path, {'actor': 'forged'}, method='PATCH', token=su)[0] == 400
assert call(row_path, {'actor': 'forged'}, method='PATCH')[0] in (403, 404)
assert call(row_path, method='DELETE')[0] in (403, 404)
assert call(row_path, method='DELETE', token=su)[0] == 204

print(f'Audit log: {len(rows)} lifecycle rows in order with actor, agent and origin; cursor, limit, project, scope and append-only passed')
