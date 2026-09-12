#!/usr/bin/env python3
"""Real board/API deletion reviews: no mutation until current impact is accepted."""
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

api, board = sys.argv[1:]


def record(method, collection, data=None, ident='', token=None):
    req = urllib.request.Request(
        f'{api}/api/collections/{collection}/records' + (f'/{ident}' if ident else ''),
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type': 'application/json',
                 **({'Authorization': f'Bearer {os.environ["LLL_TOKEN"] if token is None else token}'}
                    if token != '' else {})}, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        body = response.read()
        return json.loads(body) if body else None


def delete(kind, ident, **fields):
    req = urllib.request.Request(
        f'{board}/settings/{kind}?del=1',
        data=urllib.parse.urlencode(dict(id=ident, **fields)).encode(),
        headers={'Cookie': f'lll_board={os.environ["LLL_TEST_BOARD_TOKEN"]}'})
    with urllib.request.urlopen(req, timeout=10) as response:
        return html.unescape(response.read().decode())


admin_password = os.environ['LLL_ADMIN_PASSWORD']
auth_request = urllib.request.Request(
    f'{api}/api/collections/_superusers/auth-with-password',
    data=json.dumps(dict(identity=os.environ['LLL_ADMIN_EMAIL'], password=admin_password)).encode(),
    headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(auth_request, timeout=10) as response:
    admin_token = json.load(response)['token']

team = next(t for t in record('GET', 'teams')['items'] if t['key'] == 'ENG')
created = []


def create(collection, data, token=None):
    if collection == 'projects':
        data = dict(data, status='planned')
    item = record('POST', collection, data, token=token)
    created.append((collection, item['id']))
    return item


try:
    for kind, collection, field in [('label', 'labels', 'labels'), ('project', 'projects', 'project')]:
        entity = create(collection, dict(name=f"Deletion {kind}'s <review>", team=team['id']))
        link = [entity['id']] if field == 'labels' else entity['id']
        issue = create('issues', dict(title='Deletion relation probe', team=team['id'],
                                      state='todo', **{field: link}))
        review = delete(kind, entity['id'], name='forged name')
        assert f'removes the {kind} from 1 issue(s)' in review, review
        assert entity['name'] in review and 'forged name' not in review
        assert record('GET', 'issues', ident=issue['id'])[field] == link
        record('GET', collection, ident=entity['id'])
        # Even an explicit confirmation cannot use an outdated impact count.
        second = create('issues', dict(title='Concurrent reference probe', team=team['id'],
                                       state='todo', **{field: link}))
        stale = delete(kind, entity['id'], confirmed='1', expected='1')
        assert 'count changed' in stale and f'from 2 issue(s)' in stale, stale
        assert record('GET', 'issues', ident=second['id'])[field] == link
        for invalid in ['', '-1', 'not-a-count']:
            assert 'count changed' in delete(kind, entity['id'], confirmed='1', expected=invalid)
            record('GET', collection, ident=entity['id'])
        delete(kind, entity['id'], confirmed='1', expected='2')
        for item in [issue, second]:
            saved = record('GET', 'issues', ident=item['id'])
            assert saved[field] == ([] if field == 'labels' else ''), saved
            assert saved['title'] == item['title']
        try:
            record('GET', collection, ident=entity['id'])
            raise AssertionError('confirmed deletion left record present')
        except urllib.error.HTTPError as error:
            assert error.code == 404
    foreign = create('teams', dict(key='DELTEST', name='Deletion scope probe'))
    for kind, collection in [('label', 'labels'), ('project', 'projects')]:
        entity = create(collection, dict(name='Foreign deletion probe', team=foreign['id']))
        refused = delete(kind, entity['id'], confirmed='1', expected='0')
        assert 'not in this team' in refused, refused
        record('GET', collection, ident=entity['id'])
    # LLL-341: references span teams; ordinary API clients cannot bypass admin.
    for assigned, authored in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        member = create('members', dict(name=f'Review member {assigned}{authored}',
            email=f'review-{assigned}{authored}@example.test', password='fixture-member-pass',
            passwordConfirm='fixture-member-pass'))
        ident = member['id']
        issue = create('issues', dict(title='Member removal history', team=foreign['id'],
            state='todo', assignee=ident if assigned else ''))
        comments = []
        if authored:
            comments.append(create('comments', dict(issue=issue['id'], author=ident,
                body='Original comment history'), token=admin_token))
        for token in ['', os.environ['LLL_TOKEN']]:
            try:
                record('DELETE', 'members', ident=ident, token=token)
                raise AssertionError('non-admin API deleted member')
            except urllib.error.HTTPError as error:
                assert error.code in (401, 403, 404), error.code
            record('GET', 'members', ident=ident)
        preview = delete('member', ident)
        assert f'{assigned} issue assignment(s)' in preview, preview
        assert f'{authored} comment author reference(s)' in preview, preview
        assert 'name="admin_password"' in preview
        expected = dict(confirmed='1', expected_assigned=assigned, expected_authored=authored)
        for password in ['', 'wrong-admin-password']:
            refusal = delete('member', ident, admin_password=password, **expected)
            assert 'admin password' in refusal, refusal
            record('GET', 'members', ident=ident)
            assert record('GET', 'issues', ident=issue['id'])['assignee'] == (ident if assigned else '')
        # Admin authentication alone is not confirmation of the current impact.
        preview = delete('member', ident, admin_password=admin_password)
        assert 'Delete account' in preview
        comments.append(create('comments', dict(issue=issue['id'], author=ident,
            body='Added after review'), token=admin_token))
        stale = delete('member', ident, admin_password=admin_password, **expected)
        assert 'references changed' in stale, stale
        assert f'{authored + 1} comment author reference(s)' in stale
        assert admin_password not in stale
        record('GET', 'members', ident=ident)
        expected['expected_authored'] = authored + 1
        delete('member', ident, admin_password=admin_password, **expected)
        try:
            record('GET', 'members', ident=ident)
            raise AssertionError('confirmed account deletion left member present')
        except urllib.error.HTTPError as error:
            assert error.code == 404
        saved = record('GET', 'issues', ident=issue['id'])
        assert saved['assignee'] == '' and saved['title'] == issue['title']
        for comment in comments:
            saved = record('GET', 'comments', ident=comment['id'])
            assert saved['author'] == '' and saved['body'] == comment['body'], saved
finally:
    for collection, ident in reversed(created):
        try:
            record('DELETE', collection, ident=ident, token=admin_token)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise

print('Settings deletion: review, stale impact, explicit confirmation, relation preservation and team scope passed')
print('Member deletion: admin boundary, all reference combinations, stale review and retained history passed')
