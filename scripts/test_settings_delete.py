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


def record(method, collection, data=None, ident=''):
    req = urllib.request.Request(
        f'{api}/api/collections/{collection}/records' + (f'/{ident}' if ident else ''),
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization': f'Bearer {os.environ["LLL_TOKEN"]}',
                 'Content-Type': 'application/json'}, method=method)
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


team = next(t for t in record('GET', 'teams')['items'] if t['key'] == 'ENG')
created = []


def create(collection, data):
    item = record('POST', collection, data)
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
finally:
    for collection, ident in reversed(created):
        try:
            record('DELETE', collection, ident=ident)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise

print('Settings deletion: review, stale impact, explicit confirmation, relation preservation and team scope passed')
