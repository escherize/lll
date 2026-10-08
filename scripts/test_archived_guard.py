#!/usr/bin/env python3
"""LLL-660: an archived team is read-only, and the guard list cannot drift.

Walks the LIVE schema: every collection with a relation to teams or issues
must be either guarded (gopb/team_writes.go archivedGuarded, read from the
source) or exempt here with its reason. Then proves the guard on a running
server: a superuser's update and delete of each guarded record in an
archived team answer 403, and the exempt favorites still work.
"""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
repo = Path(__file__).resolve().parent.parent

# Related to a team or an issue, and deliberately not refused when the team
# is archived. A new collection lands in neither list and fails this test.
EXEMPT = {
    'teams': 'the archive flag itself: unarchiving is a team update',
    'members': 'access lists name teams; who may see a team must stay changeable while it is archived',
    'invites': 'grant access to teams; account administration, independent of archiving',
    'favorites': "a bookmark of an issue, not the team's data; starring changes nothing in the team",
    'issue_counters': 'server-kept numbering (LLL-678): no request writes it, and an archived team creates no issues',
    'link_viewers': "a team link's read-only reader (LLL-658); only gopb writes it, and it never writes a team",
}


def guarded_in_source():
    text = (repo / 'gopb' / 'team_writes.go').read_text()
    match = re.search(r'var archivedGuarded = \[\]string\{([^}]*)\}', text)
    assert match, 'archivedGuarded not found in gopb/team_writes.go'
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def call(base, path, body=None, token='', method=None):
    hdrs = {'Content-Type': 'application/json'}
    if token:
        hdrs['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, method=method, headers=hdrs,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        resp = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        resp = e
    text = resp.read().decode()
    try:
        text = json.loads(text)
    except ValueError:
        pass
    return resp.status, text


GUARDED = guarded_in_source()
assert not GUARDED & set(EXEMPT), GUARDED & set(EXEMPT)

with tempfile.TemporaryDirectory(prefix='lll-archived-guard-') as directory:
    root = Path(directory)
    home = root / 'home'
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(home), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='LIVE',
               LLL_BIND='127.0.0.1', USER='guard-owner', LLL_ADMIN_EMAIL='guard@example.invalid',
               LLL_ADMIN_PASSWORD='local-archived-guard-password', LLL_BOARD_TOKEN='local-archived-guard-board')
    log = root / 'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        api = wait_for_endpoints(log)['db_url']
        su = call(api, '/api/collections/_superusers/auth-with-password',
                  {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})[1]['token']

        # --- the schema: every relation to teams or issues is classified ---
        collections = call(api, '/api/collections?perPage=200', token=su)[1]['items']
        ids = {c['name']: c['id'] for c in collections}
        related = {c['name'] for c in collections
                   if any(f.get('type') == 'relation' and f.get('collectionId') in (ids['teams'], ids['issues'])
                          for f in c['fields'])} | {'teams'}
        unclassified = related - GUARDED - set(EXEMPT)
        assert not unclassified, f'collections relating to teams or issues, neither guarded nor exempt: {sorted(unclassified)}'
        stale = (GUARDED | set(EXEMPT)) - related
        assert not stale, f'classified collections that no longer relate to teams or issues: {sorted(stale)}'

        # --- fixtures in FROZEN, then archive it ---
        def make(collection, body):
            code, rec = call(api, f'/api/collections/{collection}/records', body, su)
            assert code == 200, (collection, code, rec)
            return rec

        frozen = make('teams', {'key': 'FROZEN', 'name': 'Frozen'})
        issue = make('issues', {'team': frozen['id'], 'title': 'frozen work', 'state': 'todo'})
        member = call(api, '/api/collections/members/records?perPage=1', token=su)[1]['items'][0]
        code, claim = call(api, f"/api/lll/issues/{issue['id']}/claim", {'member': member['id']}, su)
        assert code == 200, claim
        claim = call(api, '/api/collections/claims/records?perPage=1', token=su)[1]['items'][0]
        records = {
            'issues': issue,
            'claims': claim,
            'comments': make('comments', {'issue': issue['id'], 'body': 'frozen comment'}),
            'docs': make('docs', {'team': frozen['id'], 'slug': 'frozen-doc', 'title': 't', 'kind': 'note', 'body': 'b'}),
            'labels': make('labels', {'team': frozen['id'], 'name': 'frozen-label'}),
            'projects': make('projects', {'team': frozen['id'], 'name': 'Frozen project', 'status': 'planned'}),
            'webhooks': make('webhooks', {'team': frozen['id'], 'url': 'https://example.test/hook'}),
        }
        assert set(records) == GUARDED, f'add a fixture for {sorted(GUARDED - set(records))}'
        assert call(api, f"/api/collections/teams/records/{frozen['id']}", {'archived': True}, su, 'PATCH')[0] == 200

        # --- every guarded record refuses a superuser's update and delete ---
        for collection, rec in records.items():
            for method, body in (('PATCH', {}), ('DELETE', None)):
                code, answer = call(api, f"/api/collections/{collection}/records/{rec['id']}", body, su, method)
                assert code == 403 and 'FROZEN is archived' in json.dumps(answer), (collection, method, code, answer)
        code, answer = call(api, '/api/collections/comments/records', {'issue': issue['id'], 'body': 'new'}, su)
        assert code == 403, (code, answer)
        # Exempt: a favorite of an archived team's issue still works.
        assert call(api, '/api/collections/favorites/records', {'issue': issue['id']}, su)[0] == 200

        # Control: unarchived, the same delete goes through.
        assert call(api, f"/api/collections/teams/records/{frozen['id']}", {'archived': False}, su, 'PATCH')[0] == 200
        assert call(api, f"/api/collections/labels/records/{records['labels']['id']}", token=su, method='DELETE')[0] == 204
    finally:
        child.terminate()
        child.wait(timeout=30)

print(f'Archived guard: {len(GUARDED)} guarded, {len(EXEMPT)} exempt, schema fully classified; superuser writes refused')
