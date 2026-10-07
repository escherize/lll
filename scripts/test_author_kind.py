#!/usr/bin/env python3
"""Author kind on comments (LLL-610): person vs bot, and a bot's owner, in
'issue view', --raw, --json and the board's issue page and ?raw."""
import json
import os
import re
import subprocess
import sys
import urllib.request

binary, api, board = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='AK610')
su = os.environ['LLL_TEST_SUPERUSER_TOKEN']
cookie = 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN']


def cli(*args):
    p = subprocess.run([binary, *args], env=env, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return p.stdout


def admin(path, body):
    req = urllib.request.Request(api + path, data=json.dumps(body).encode(), headers={
        'Authorization': 'Bearer ' + su, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def web(path):
    req = urllib.request.Request(board + path, headers={'Cookie': cookie})
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode()


def member(name, **extra):
    return admin('/api/collections/members/records', dict(
        name=name, email=name + '@author-kind.invalid', password='author-kind-123',
        passwordConfirm='author-kind-123', **extra))


cli('team', 'create', '-k', 'AK610', '-n', 'Author kinds')
issue = json.loads(cli('issue', 'create', 'Who wrote this', '--json'))
key = 'AK610-1'
owner = member('ak-owner', kind='person')
owned = member('bot-ak-owned', kind='bot', owner=owner['id'])
orphan = member('bot-ak-orphan', kind='bot')
for author, body in ((owner, 'person words'), (owned, 'owned bot words'), (orphan, 'orphan bot words')):
    admin('/api/collections/comments/records', dict(issue=issue['id'], author=author['id'], body=body))

# LLL-621: comments list by (created, id). PocketBase stamps 'created' to the
# millisecond, so two of these fixtures can tie and then sort by their random
# ids. Every assertion below finds a comment by its author, never by position.
view = cli('issue', 'view', key)
assert re.search(r'^#[1-3] ak-owner \(', view, re.M), view
assert re.search(r'^#[1-3] bot-ak-owned \[bot via ak-owner\] \(', view, re.M), view
assert re.search(r'^#[1-3] bot-ak-orphan \[bot\] \(', view, re.M), view

raw = cli('issue', 'view', key, '--raw')
assert '- **ak-owner** (' in raw, raw
assert '- **bot-ak-owned** [bot via ak-owner] (' in raw, raw
assert '- **bot-ak-orphan** [bot] (' in raw, raw

authors = {c['expand']['author']['name']: c['expand']['author']
           for c in json.loads(cli('issue', 'view', key, '--json'))['comments']}
assert sorted(authors) == ['ak-owner', 'bot-ak-orphan', 'bot-ak-owned'], authors
person, bot_owned, bot_orphan = authors['ak-owner'], authors['bot-ak-owned'], authors['bot-ak-orphan']
assert person['kind'] == 'person' and 'expand' not in person, person
assert bot_owned['kind'] == 'bot' and bot_owned['owner'] == owner['id'], bot_owned
assert bot_owned['expand']['owner'] == dict(id=owner['id'], name='ak-owner'), bot_owned
assert bot_orphan['kind'] == 'bot' and 'expand' not in bot_orphan, bot_orphan

page = web('/issue/' + key)
assert '<b>ak-owner</b> · ' in page and '<b>ak-owner</b> · via' not in page, page
assert '<b>bot-ak-owned</b> · via ak-owner · ' in page, page
assert '<b>bot-ak-orphan</b> · ' in page and '<b>bot-ak-orphan</b> · via' not in page, page
page_raw = web('/issue/' + key + '?raw')
assert '- **bot-ak-owned** [bot via ak-owner] (' in page_raw, page_raw
assert '- **bot-ak-orphan** [bot] (' in page_raw, page_raw
assert '- **ak-owner** (' in page_raw, page_raw
print('Author kind: person vs bot and the bot owner in view, --raw, --json and the board passed')
