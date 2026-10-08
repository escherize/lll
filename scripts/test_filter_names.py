#!/usr/bin/env python3
"""Comma-name refusals through CLI, PocketBase and board settings."""
import html
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

binary, api, board = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='NAMES')


def cli(*args):
    return subprocess.run([binary, *args], env=env, capture_output=True, text=True, timeout=30)


def record(collection, body=None, ident=''):
    req = urllib.request.Request(api + '/api/collections/' + collection + '/records' + ('/' + ident if ident else ''),
        data=json.dumps(body).encode() if body is not None else None,
        method='PATCH' if ident and body is not None else None,
        headers={'Authorization': 'Bearer ' + env['LLL_TOKEN'], 'Content-Type': 'application/json'})
    try:
        response = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def refused(message):
    assert 'commas' in message and 'board filters' in message, message


status, team = record('teams', {'key': 'NAMES', 'name': 'Filter name validation'})
assert status == 200, team
for kind, collection, extra in [('label', 'labels', {'color': '#123456'}),
                                 ('project', 'projects', {'status': 'planned'})]:
    invalid = 'Q3, infra'
    payload = dict(name=invalid, team=team['id'], **extra)
    status, result = record(collection, payload)
    assert status == 400, (status, result)
    refused(json.dumps(result))
    p = cli(kind, 'create', invalid)
    assert p.returncode != 0, p.stdout
    refused(p.stderr)
    # Multibyte text and ordinary punctuation remain valid.
    valid = "café 集合: owner's queue"
    p = cli(kind, 'create', valid)
    assert p.returncode == 0, p.stderr
    status, rows = record(collection)
    assert status == 200
    entity = next(r for r in rows['items'] if r['team'] == team['id'] and r['name'] == valid)
    p = cli(kind, 'edit', valid, '-n', invalid)
    assert p.returncode != 0, p.stdout
    refused(p.stderr)
    # Invalid names are checked before resolving the old name.
    p = cli(kind, 'edit', 'no such old name', '-n', invalid)
    assert p.returncode != 0
    refused(p.stderr)
    status, result = record(collection, {'name': invalid, **extra}, entity['id'])
    assert status == 400, (status, result)
    refused(json.dumps(result))
    for ident in ('', entity['id']):
        req = urllib.request.Request(board + '/t/NAMES/settings/' + kind,
            data=urllib.parse.urlencode(dict(id=ident, name=invalid, **extra)).encode(),
            headers={'Cookie': 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN'], 'Origin': board})
        with urllib.request.urlopen(req, timeout=20) as response:
            reply = html.unescape(response.read().decode())
        refused(reply)
        assert 'id="settings"' not in reply, 'a rejected write must not redraw the form and discard drafts'
    status, after = record(collection, ident=entity['id'])
    assert status == 200 and after['name'] == valid
    assert all(after[field] == entity[field] for field in extra), (entity, after)
    status, rows = record(collection)
    assert status == 200
    owned = [r for r in rows['items'] if r['team'] == team['id']]
    assert len(owned) == 1 and owned[0]['name'] == valid, owned
    p = cli(kind, 'edit', valid, '-n', 'Renamed 集合')
    assert p.returncode == 0, p.stderr
print('Filter names: comma create/rename refused through CLI/API/settings, no partial writes or draft redraw; Unicode and valid renames passed')
