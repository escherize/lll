#!/usr/bin/env python3
"""Doc authors (LLL-618): the server records who created a doc from the
caller's token, a member cannot forge or change it, and 'doc view', --json,
--raw and the board's doc page and ?raw show a person, a bot with its owner,
and an authorless doc."""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

binary, api, board = sys.argv[1:]
TEAM = 'DA618'
su = os.environ['LLL_TEST_SUPERUSER_TOKEN']
cookie = 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN']
env = dict(os.environ, LLL_URL=api, LLL_TEAM=TEAM)


def cli(*args, token=None):
    e = dict(env, LLL_TOKEN=token) if token else env
    p = subprocess.run([binary, *args], env=e, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, (args, p.stderr)
    return p.stdout


def call(method, path, token, body=None):
    """(status, decoded body) of one PocketBase request; never raises on 4xx."""
    req = urllib.request.Request(api + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def ok(method, path, token, body=None):
    status, out = call(method, path, token, body)
    assert 200 <= status < 300, (method, path, status, out)
    return out


def web(path):
    req = urllib.request.Request(board + path, headers={'Cookie': cookie})
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode()


def member(name, **extra):
    return ok('POST', '/api/collections/members/records', su, dict(
        name=name, email=name + '@doc-author.invalid', password='doc-author-123',
        passwordConfirm='doc-author-123', **extra))


def token(m):
    return ok('POST', '/api/collections/members/impersonate/' + m['id'], su, dict(duration=3600))['token']


def record(slug):
    return json.loads(cli('doc', 'view', slug, '--json'))


cli('team', 'create', '-k', TEAM, '-n', 'Doc authors')
team_id = ok('GET', "/api/collections/teams/records?filter=key%3D'" + TEAM + "'", su)['items'][0]['id']
owner = member('da-owner', kind='person')
bot = member('bot-da', kind='bot', owner=owner['id'])
owner_tok, bot_tok = token(owner), token(bot)

# Every write path sets the author from the token, never from the body:
# 'doc create' as a person, 'finding create' as a bot, the raw API as a bot,
# and a superuser write, which has no member and stays authorless.
cli('doc', 'create', '-s', 'person-doc', '-t', 'Person doc', '-b', 'person body', token=owner_tok)
cli('finding', 'create', 'bot-finding', '-t', 'Bot finding', '-b', 'bot body', token=bot_tok)
ok('POST', '/api/collections/docs/records', bot_tok,
   dict(team=team_id, slug='bot-raw', title='Bot raw', kind='wiki', body='raw body'))
ok('POST', '/api/collections/docs/records', su,
   dict(team=team_id, slug='no-author', title='Nobody', kind='wiki', body='orphan body'))

person_rec, bot_rec = record('person-doc'), record('bot-finding')
assert person_rec['author'] == owner['id'], person_rec
assert bot_rec['author'] == bot['id'], bot_rec
assert record('bot-raw')['author'] == bot['id']
none_rec = record('no-author')
assert none_rec['author'] == '' and 'author' not in none_rec.get('expand', {}), none_rec

# Forging: a member naming any author on create is refused, itself included,
# and nothing is written.
for forged in (owner['id'], bot['id']):
    status, out = call('POST', '/api/collections/docs/records', owner_tok,
                       dict(team=team_id, slug='forged', title='Forged', kind='wiki', author=forged))
    assert status >= 400, ('forged create was accepted', forged, out)
    assert status < 500, out
p = subprocess.run([binary, 'doc', 'view', 'forged'], env=env, capture_output=True, text=True, timeout=30)
assert p.returncode != 0 and 'no doc with slug' in p.stderr, (p.stdout, p.stderr)

# Immutable after create: re-attributing is refused, the author is unchanged,
# and an ordinary edit through the same rule still works.
for tok in (owner_tok, bot_tok):
    status, out = call('PATCH', '/api/collections/docs/records/' + person_rec['id'], tok, dict(author=bot['id']))
    assert status >= 400 and status < 500, ('author change was accepted', status, out)
status, out = call('PATCH', '/api/collections/docs/records/' + none_rec['id'], owner_tok, dict(author=owner['id']))
assert status >= 400 and status < 500, ('claiming an authorless doc was accepted', status, out)
assert record('person-doc')['author'] == owner['id']
assert record('no-author')['author'] == ''
cli('doc', 'edit', 'person-doc', '-t', 'Person doc, edited', token=bot_tok)
assert record('person-doc')['author'] == owner['id']

# --json: the record with the author expanded, and a bot author's owner.
person_rec, bot_rec = record('person-doc'), record('bot-finding')
assert person_rec['expand']['author']['name'] == 'da-owner', person_rec
assert person_rec['expand']['author']['kind'] == 'person', person_rec
assert bot_rec['expand']['author']['name'] == 'bot-da', bot_rec
assert bot_rec['expand']['author']['expand']['owner']['name'] == 'da-owner', bot_rec

# Text view: the same marker comments use.
view = cli('doc', 'view', 'person-doc')
assert 'Author:    da-owner\n' in view, view
view = cli('doc', 'view', 'bot-finding')
assert 'Author:    bot-da [bot via da-owner]\n' in view, view
view = cli('doc', 'view', 'no-author')
assert 'Author:' not in view, view

# --raw stays the body and nothing else: it is the pipe form (e2e.sh pins it
# byte for byte), so the author is not prepended to it.
assert cli('doc', 'view', 'bot-finding', '--raw') == 'bot body'
assert cli('doc', 'view', 'no-author', '--raw') == 'orphan body'

# The board's doc page and its ?raw.
base = '/t/' + TEAM + '/doc/'
AUTHOR = '<span class="k">Author</span>'
page = web(base + 'bot-finding')
prop = page.split(AUTHOR, 1)[1].split('</div>', 1)[0]
assert 'title="bot member"' in prop and 'bot-da · via da-owner</span>' in prop, prop
page = web(base + 'person-doc')
prop = page.split(AUTHOR, 1)[1].split('</div>', 1)[0]
assert 'da-owner</span>' in prop and 'via' not in prop and 'bot member' not in prop, prop
assert AUTHOR not in web(base + 'no-author')

assert 'Author: bot-da [bot via da-owner]\n' in web(base + 'bot-finding?raw')
assert 'Author: da-owner\n' in web(base + 'person-doc?raw')
assert 'Author:' not in web(base + 'no-author?raw')
print('Doc author: set from the token, unforgeable, immutable, shown in view, --json, --raw and the board passed')
