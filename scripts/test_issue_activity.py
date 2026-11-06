#!/usr/bin/env python3
"""Issue activity materialization through native CLI and records API."""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

binary, api = sys.argv[1:]
assert urllib.parse.urlsplit(api).hostname == '127.0.0.1', 'requires an isolated board'

with tempfile.TemporaryDirectory(prefix='lll-activity-config-') as home:
    env = dict(os.environ, LLL_URL=api, LLL_TEAM='ACTDATE', LLL_CONFIG_HOME=home)

    def cli(*args):
        p = subprocess.run([binary, *args], env=env, capture_output=True, text=True, timeout=30)
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout) if '--json' in args else p.stdout

    def request(path, body=None, method=None):
        req = urllib.request.Request(api + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + env['LLL_TOKEN']})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    cli('team', 'create', '--key', 'ACTDATE', '-n', 'Activity dates')
    issue = cli('issue', 'create', 'Activity fixture', '--json')
    assert issue['last_activity']
    path = '/api/collections/issues/records/' + issue['id']
    original_updated = issue['updated']
    # A no-op spoof must neither forge the date nor create audit activity.
    request(path, {'last_activity': '2099-01-01T00:00:00Z'}, 'PATCH')
    prior = request(path)
    assert prior['last_activity'] == issue['last_activity']
    original_updated = prior['updated']
    time.sleep(0.02)
    comment = cli('issue', 'comment', issue['key'], '-b', 'Progress', '--json')
    current = request(path)
    assert current['last_activity'] > prior['last_activity']
    assert current['updated'] == original_updated
    comment_path = '/api/collections/comments/records/' + comment['id']
    for method, body in [('PATCH', {'body': 'Edited progress'}), ('DELETE', None)]:
        time.sleep(0.02)
        prior = current
        request(comment_path, body, method)
        current = request(path)
        assert current['last_activity'] > prior['last_activity']
        assert current['updated'] == original_updated
    # The new materialized field must survive raw-record JSON enrichment.
    listed = cli('issue', 'list', '--json')['items']
    assert listed[0]['last_activity'] == current['last_activity']
    after_issue_edit = (datetime.datetime.fromisoformat(original_updated.replace('Z', '+00:00'))
                        + datetime.timedelta(milliseconds=1)).isoformat()
    assert cli('issue', 'list', '--since', after_issue_edit, '--json')['items'] == []
    cli('issue', 'claim', issue['key'])
    prior = request(path)
    time.sleep(0.02)
    cli('issue', 'claim', issue['key'], '--renew')
    current = request(path)
    assert current['last_activity'] > prior['last_activity']
    assert current['updated'] == prior['updated']
    time.sleep(0.02)
    cli('issue', 'release', issue['key'])
    current = request(path)
    assert current['last_activity'] >= prior['last_activity']
    assert cli('issue', 'view', issue['key'], '--json')['last_activity'] == current['last_activity']

print('Issue activity: native create/list/view, comment edits/deletion, claim renewal/release, spoof protection and unchanged --since semantics passed')
