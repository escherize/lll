#!/usr/bin/env python3
"""Identity fields are the server's word (LLL-681).

Every field that says WHO made or owns a record is set by the server, or by a
superuser, and a member cannot set it to someone else on create or move it
after: issues.creator and origin, members.owner and kind, favorites.member and
views.member, plus the guards that already held (comments.author, author_kind
and server_record, webhooks.creator, claims, issue_counters, the Batch API).
Superusers keep every write: they repair and import attribution."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def call(base, path, body=None, token='', method=None):
    """(status, parsed body). Never raises on HTTP errors."""
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
        return resp.status, json.loads(text)
    except ValueError:
        return resp.status, text


with tempfile.TemporaryDirectory(prefix='lll-identity-') as directory:
    root = Path(directory)
    home = root / 'home'
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(home), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='IDF',
               LLL_BIND='127.0.0.1', USER='identity-owner', LLL_ADMIN_EMAIL='identity@example.invalid',
               LLL_ADMIN_PASSWORD='local-identity-password', LLL_BOARD_TOKEN='local-identity-board')
    log = root / 'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        api = wait_for_endpoints(log)['db_url']
        _, su = call(api, '/api/collections/_superusers/auth-with-password',
                     {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})
        su = su['token']

        def ok(path, body=None, token=su, method=None):
            status, out = call(api, path, body, token, method)
            assert 200 <= status < 300, (method, path, body, status, out)
            return out

        holes = []

        def refused(path, body=None, token=su, method=None):
            # Collected rather than raised, so one run lists every hole.
            status, _ = call(api, path, body, token, method)
            if status not in (400, 403, 404):
                holes.append((method or 'POST', path, body, status))

        _, teams = call(api, '/api/collections/teams/records', token=su)
        team = next(t for t in teams['items'] if t['key'] == 'IDF')

        def person(name, **extra):
            return ok('/api/collections/members/records', dict(
                name=name, email=name + '@identity.invalid', password='identity-123',
                passwordConfirm='identity-123', kind='person', **extra))

        def token(m):
            return ok(f"/api/collections/members/impersonate/{m['id']}", {'duration': 3600})['token']

        alice = person('alice')  # full: scope all, read-write
        bob = person('bob')
        guest = person('guest', scope='teams', teams=[team['id']])  # scoped read-write
        a_tok, g_tok = token(alice), token(guest)
        members = '/api/collections/members/records'

        # --- issues.creator and origin: set on create, then fixed ---------------
        issue = ok('/api/collections/issues/records', {
            'team': team['id'], 'title': 'mine', 'state': 'todo',
            'creator': bob['id'], 'origin': {'host': 'h', 'tool': 'cli'}}, a_tok)
        assert issue['creator'] == alice['id'], issue  # the token, not the body
        path = f"/api/collections/issues/records/{issue['id']}"
        for token_ in (a_tok, g_tok):
            for body in ({'creator': bob['id']}, {'creator': ''}, {'origin': {'host': 'forged'}},
                         {'origin': None}, {'title': 'x', 'creator': bob['id']}):
                refused(path, body, token_, 'PATCH')
        after = ok(path)
        assert (after['creator'], after['origin'], after['title']) == (alice['id'], issue['origin'], 'mine'), after
        assert ok(path, {'title': 'renamed'}, a_tok, 'PATCH')['title'] == 'renamed'
        # A superuser repairs attribution.
        assert ok(path, {'creator': bob['id'], 'origin': {'host': 'fixed'}}, su, 'PATCH')['creator'] == bob['id']

        # --- members.owner and kind on create ------------------------------------
        def new(name, **extra):
            return dict(name=name, email=name + '@identity.invalid', password='identity-123',
                        passwordConfirm='identity-123', **extra)
        for token_ in (a_tok, g_tok):
            refused(members, new('bot-for-bob', kind='bot', owner=bob['id']), token_)
            refused(members, new('bot-nobody', kind='bot'), token_)
            refused(members, new('owned-person', kind='person', owner=bob['id']), token_)
            refused(members, new('owned-self', kind='person', owner=alice['id']), token_)
            refused(members, new('kindless', owner=bob['id']), token_)
        assert ok(members, new('bot-alice', kind='bot', owner=alice['id']), a_tok)['owner'] == alice['id']
        assert ok(members, new('bot-guest', kind='bot', owner=guest['id']), g_tok)['owner'] == guest['id']
        assert ok(members, new('carol', kind='person'), a_tok)['owner'] == ''
        refused(members, new('dave', kind='person'), g_tok)  # only a full member creates a person
        assert ok(members, new('bot-bob', kind='bot', owner=bob['id']))['owner'] == bob['id']  # superuser

        # --- favorites.member and views.member -----------------------------------
        favorites, views = '/api/collections/favorites/records', '/api/collections/views/records'
        refused(favorites, {'issue': issue['id'], 'member': bob['id']}, a_tok)
        refused(favorites, {'issue': issue['id'], 'member': bob['id']}, g_tok)
        mine = ok(favorites, {'issue': issue['id'], 'member': alice['id']}, a_tok)
        shared = ok(favorites, {'issue': issue['id']}, a_tok)  # the board's, no member
        bobs_fav = ok(favorites, {'issue': issue['id'], 'member': bob['id']})  # superuser
        for fav in (mine, shared, bobs_fav):
            refused(f"{favorites}/{fav['id']}", {'member': bob['id']}, a_tok, 'PATCH')
            refused(f"{favorites}/{fav['id']}", {'member': alice['id']}, a_tok, 'PATCH')
        assert ok(f"{favorites}/{bobs_fav['id']}")['member'] == bob['id']
        refused(views, {'name': 'v', 'query': 'state=todo', 'member': bob['id']}, a_tok)
        refused(views, {'name': 'v', 'query': 'state=todo', 'member': bob['id']}, g_tok)
        view = ok(views, {'name': 'v', 'query': 'state=todo', 'member': alice['id']}, a_tok)
        ok(views, {'name': 'v', 'query': 'state=todo'}, a_tok)
        bobs_view = ok(views, {'name': 'v', 'query': 'state=todo', 'member': bob['id']})
        for v in (view, bobs_view):
            refused(f"{views}/{v['id']}", {'member': guest['id']}, a_tok, 'PATCH')
        assert ok(f"{views}/{view['id']}", {'name': 'v2'}, a_tok, 'PATCH')['name'] == 'v2'
        # Nor does a full member rewrite what another member's says.
        other = ok('/api/collections/issues/records', {'team': team['id'], 'title': 'other', 'state': 'todo'}, a_tok)
        refused(f"{favorites}/{bobs_fav['id']}", {'issue': other['id']}, a_tok, 'PATCH')
        refused(f"{views}/{bobs_view['id']}", {'name': 'renamed', 'query': 'assignee=alice'}, a_tok, 'PATCH')
        assert ok(f"{favorites}/{bobs_fav['id']}")['issue'] == issue['id']
        assert ok(f"{views}/{bobs_view['id']}")['query'] == 'state=todo'
        assert ok(f"{favorites}/{shared['id']}", {'issue': other['id']}, a_tok, 'PATCH')['member'] == ''

        # --- guards that already held stay held -----------------------------------
        comment = ok('/api/collections/comments/records',
                     {'issue': issue['id'], 'body': 'hi', 'author': bob['id']}, a_tok)
        assert comment['author'] == alice['id'], comment
        cpath = f"/api/collections/comments/records/{comment['id']}"
        refused(cpath, {'author': bob['id']}, a_tok, 'PATCH')
        refused(cpath, {'author_kind': 'system'}, a_tok, 'PATCH')
        refused(cpath, {'server_record': True}, a_tok, 'PATCH')
        refused('/api/collections/comments/records', {'issue': issue['id'], 'body': 'x', 'author_kind': 'system'}, a_tok)
        refused('/api/collections/comments/records', {'issue': issue['id'], 'body': 'x', 'server_record': True}, a_tok)
        hook = ok('/api/collections/webhooks/records',
                  {'team': team['id'], 'url': 'https://example.invalid/h', 'creator': bob['id']}, a_tok)
        assert hook['creator'] == alice['id'], hook
        refused(f"/api/collections/webhooks/records/{hook['id']}", {'creator': bob['id']}, a_tok, 'PATCH')
        refused('/api/collections/claims/records', {'issue': issue['id'], 'member': bob['id']}, a_tok)
        refused('/api/collections/issue_counters/records', {'team': team['id'], 'last': 0}, a_tok)
        refused(f"/api/collections/members/records/{alice['id']}", {'owner': bob['id']}, a_tok, 'PATCH')
        refused(f"/api/collections/members/records/{alice['id']}", {'kind': 'bot'}, a_tok, 'PATCH')
        # The Batch API is off, so no request reaches a rule through it.
        refused('/api/batch', {'requests': [{'method': 'PATCH', 'url': path, 'body': {'creator': alice['id']}}]}, a_tok, 'POST')
        assert not holes, 'accepted:\n' + '\n'.join(map(repr, holes))
        print('identity fields: ok')
    finally:
        child.terminate()
        child.wait(timeout=30)
