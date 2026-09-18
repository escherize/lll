#!/usr/bin/env python3
"""Inclusive catch-up windows and composed filters against an isolated server."""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse

binary, api = sys.argv[1:]
if urllib.parse.urlsplit(api).hostname not in ('127.0.0.1', 'localhost', '::1'):
    raise SystemExit('issue --since regression requires an isolated loopback server')
config_home = tempfile.TemporaryDirectory(prefix='lll-since-config-')
env = dict(os.environ, LLL_URL=api, LLL_TEAM='SINCE', LLL_CONFIG_HOME=config_home.name,
           LLL_SORT='created')


def cli(*args, team='SINCE'):
    result = subprocess.run([binary, *args], env=dict(env, LLL_TEAM=team),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def listed(stamp, *filters):
    return [item['id'] for item in json.loads(
        cli('issue', 'list', '--since', stamp, '--json', *filters))['items']]


def instant(record):
    return datetime.datetime.fromisoformat(record['updated'].replace('Z', '+00:00'))


cli('team', 'create', '-k', 'SINCE', '-n', 'Since fixture')
cli('team', 'create', '-k', 'SINCE2', '-n', 'Other since fixture')
cli('member', 'add', '-n', 'since-owner')
cli('label', 'create', '-n', 'delta')
old = json.loads(cli('issue', 'create', 'Before window', '--json',
                     '--assignee', 'since-owner', '--label', 'delta', '--priority', '1'))
time.sleep(0.02)
boundary = json.loads(cli('issue', 'create', 'At window', '--json',
                          '--assignee', 'since-owner', '--label', 'delta', '--priority', '3'))
time.sleep(0.02)
new = json.loads(cli('issue', 'create', 'After window', '--json', '--state', 'done',
                     '--priority', '4'))
cli('issue', 'create', 'Different team', '--json', team='SINCE2')
assert instant(old) < instant(boundary) < instant(new)
stamp = instant(boundary).isoformat()
expected = [boundary['id'], new['id']]
assert listed(stamp) == expected
assert listed(instant(old).isoformat()) == [old['id'], *expected]
offset = instant(boundary).astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
assert listed(offset.isoformat()) == expected
assert listed((instant(boundary) + datetime.timedelta(microseconds=1)).isoformat()) == [new['id']]
assert listed((instant(new) + datetime.timedelta(milliseconds=1)).isoformat()) == []
assert listed(stamp, '--state', 'todo', '--assignee', 'since-owner', '--label', 'delta') == [boundary['id']]
assert listed(stamp, '--state', 'todo', '--state', 'done') == expected
# Filtering must happen before server pagination, including the priority path.
assert listed(stamp, '--limit', '1') == [boundary['id']]
assert listed(stamp, '--limit', '1', '--page', '2') == [new['id']]
assert listed(stamp, '--sort', 'priority', '--limit', '1') == [boundary['id']]
assert 'At window' in cli('issue', 'list', '--since', stamp)
assert 'Before window' not in cli('issue', 'list', '--since', stamp)
for invalid in ('', 'yesterday', '2026-09-18', '2026-02-30T00:00:00Z',
                '2026-09-18T00:00:00+24:00', "2026-09-18T00:00:00Z' || true"):
    result = subprocess.run([binary, 'issue', 'list', '--since', invalid, '--json'],
                            env=dict(env, LLL_URL='http://127.0.0.1:1'),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and not result.stdout, result
    assert 'RFC3339' in result.stderr and '2026-09-18T00:00:00Z' in result.stderr, result.stderr
help_text = cli('issue', 'list', '--help')
for explanation in ('no deletions', 'intermediate states', 'not exactly-once', 'overlap'):
    assert explanation in help_text, explanation
print('Issue --since: inclusive UTC/offset and submillisecond bounds, scoped filters, pagination, priority, invalid input and recovery guidance passed')
