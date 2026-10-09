#!/usr/bin/env python3
"""The 1.0 CLI contract against a live board (LLL-645, docs/cli-contract.md).

Exit codes by kind, the one list envelope, RFC3339 timestamps, the issue
object's key and claim (LLL-651), --raw's claim line (LLL-638), --ready past
the first page (LLL-673), time flags in both forms, and `lll api --fail`.
"""
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
RFC3339 = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$')
ENVELOPE = ['items', 'page', 'perPage', 'totalItems', 'totalPages']


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


with tempfile.TemporaryDirectory(prefix='lll-cli-contract-') as directory:
    root = Path(directory)
    serverhome, home, work = root / 'serverhome', root / 'home', root / 'work'
    for path in (serverhome, home, work):
        path.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(serverhome), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='CON',
               LLL_BIND='127.0.0.1', USER='contract-owner', LLL_ADMIN_EMAIL='contract@example.invalid',
               LLL_ADMIN_PASSWORD='local-cli-contract-password', LLL_BOARD_TOKEN='local-cli-contract-board')
    log = root / 'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(root / 'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        endpoint = wait_for_endpoints(log)
        assert child.poll() is None
        api = endpoint['db_url']

        def request(path, body=None, token=''):
            req = urllib.request.Request(api + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json',
                                                  **({'Authorization': 'Bearer ' + token} if token else {})})
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)

        admin = request('/api/collections/_superusers/auth-with-password',
                        {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})['token']
        owner = next(m for m in request('/api/collections/members/records', token=admin)['items']
                     if m['name'] == 'contract-owner')
        token = request('/api/collections/members/impersonate/' + owner['id'], {'duration': 3600}, admin)['token']
        other = request('/api/collections/members/records',
                        {'name': 'other', 'email': 'other@example.invalid', 'password': 'other-password-1',
                         'passwordConfirm': 'other-password-1', 'kind': 'person'}, admin)
        other_token = request('/api/collections/members/impersonate/' + other['id'], {'duration': 3600}, admin)['token']
        (work / '.lll.toml').write_text(f'url = "{api}"\nteam = "CON"\n')
        base = {k: v for k, v in env.items() if not k.startswith(('LLL_', 'XDG_'))}
        base.update(HOME=str(home), LLL_URL=api, LLL_TOKEN=token, LC_ALL='C')

        def run(*args, token_override=None, stdin=''):
            current = dict(base)
            if token_override is not None:
                current['LLL_TOKEN'] = token_override
                if token_override == '':
                    del current['LLL_TOKEN']
            return subprocess.run([binary, *args], cwd=work, env=current, text=True, capture_output=True,
                                  timeout=30, input=stdin)

        def code(expected, *args, **kw):
            result = run(*args, **kw)
            assert result.returncode == expected, (args, result.returncode, result.stdout, result.stderr)
            return result

        def as_json(*args, **kw):
            result = code(0, *args, **kw)
            return json.loads(result.stdout)

        # The kind travels inside the error text as a control-character tag;
        # it must never reach the terminal.
        def clean(result):
            for stream in (result.stdout, result.stderr):
                assert '\x1d' not in stream and 'lll:' not in stream, stream

        for title in ('first', 'second', 'third'):
            code(0, 'issue', 'create', '-t', title)
        code(0, 'issue', 'close', 'CON-1')

        # --- exit codes (D1) ---
        clean(code(2, 'issue', 'list', '--bogus'))
        clean(code(2, 'bogus'))
        clean(code(2, 'issue', 'frob'))
        clean(code(2, 'issue', 'view', 'not-an-id'))
        clean(code(2, 'issue', 'list', '--since', 'yesterday'))
        for bad in (['issue', 'list', '--limit', '0'], ['issue', 'list', '--ready', '--blocked'],
                    ['issue', 'list', '--state', 'bogus'], ['issue', 'list', '--sort', 'bogus'],
                    ['issue', 'create', 't', '--priority', '9'], ['issue', 'update', 'CON-2'],
                    ['issue', 'assign'], ['finding', 'confirm']):
            clean(code(2, *bad))
        clean(code(3, 'issue', 'view', 'CON-99'))
        clean(code(3, 'doc', 'view', 'no-such-doc'))
        clean(code(3, 'issue', 'list', '--label', 'no-such-label'))
        assert code(0, 'issue', 'list', '-h').stdout.startswith('usage:')
        code(0, 'issue', 'claim', 'CON-2', '--agent', 'wt-a')
        held = code(4, 'issue', 'claim', 'CON-2', token_override=other_token)
        clean(held)
        assert 'already claimed by contract-owner' in held.stderr, held.stderr
        assert 'POST' not in held.stderr and '{"' not in held.stderr, held.stderr
        clean(code(4, 'issue', 'release', 'CON-2', token_override=other_token))
        clean(code(4, 'issue', 'release', 'CON-3'))
        clean(code(4, 'issue', 'delete', 'CON-3'))
        clean(code(6, 'issue', 'list', token_override=''))
        clean(code(6, 'issue', 'list', token_override='not.a.token'))
        # An empty agenda: CON-3 is the only ready issue; claim it, then ask.
        code(0, 'issue', 'claim', 'CON-3')
        clean(code(5, 'issue', 'next'))
        code(0, 'issue', 'release', 'CON-3')

        # --- the list envelope, one shape whatever the flags (D2, LLL-673) ---
        plain = as_json('issue', 'list', '--json')
        assert sorted(plain) == ENVELOPE and plain['totalItems'] == 3, plain
        # CON-1 is done and first: one page of the raw order holds no ready issue.
        for flags in (['--ready'], ['--sort', 'priority'], ['--blocked'], []):
            page = as_json('issue', 'list', '--limit', '1', '--json', *flags)
            assert sorted(page) == ENVELOPE and isinstance(page['items'], list), (flags, page)
        ready = as_json('issue', 'list', '--ready', '--limit', '1', '--json')
        assert [i['key'] for i in ready['items']] == ['CON-2'] and ready['totalItems'] == 2, ready
        ready2 = as_json('issue', 'list', '--ready', '--limit', '1', '--page', '2', '--json')
        assert [i['key'] for i in ready2['items']] == ['CON-3'] and ready2['totalPages'] == 2, ready2
        assert as_json('issue', 'list', '--blocked', '--json')['items'] == []
        for noun in ('label', 'project', 'doc', 'finding', 'team', 'member', 'webhook'):
            listed = as_json(noun, 'list', '--json')
            assert sorted(listed) == ENVELOPE and isinstance(listed['items'], list), (noun, listed)
        assert sorted(as_json('search', 'zzzz-nothing', '--json')) == ENVELOPE

        # --- empty-state lines on stderr, stdout empty ---
        for noun, line in (('label', 'no labels'), ('project', 'no projects'), ('webhook', 'no webhooks')):
            empty = code(0, noun, 'list')
            assert empty.stdout == '' and empty.stderr.strip() == line, (noun, empty.stdout, empty.stderr)

        # --- the issue object: key, claim, RFC3339 (LLL-651) ---
        items = {i['key']: i for i in plain['items']}
        claim = items['CON-2']['claim']
        assert claim['holder'] == 'contract-owner' and claim['agent'] == 'wt-a', claim
        assert RFC3339.match(claim['claimed']) and RFC3339.match(claim['renewed']), claim
        assert items['CON-3']['claim'] is None
        assert RFC3339.match(items['CON-3']['created']) and RFC3339.match(items['CON-3']['updated'])
        view = as_json('issue', 'view', 'CON-2', '--json')
        assert view['key'] == 'CON-2' and view['claim']['holder'] == 'contract-owner'
        assert all(RFC3339.match(view['expand']['team'][k]) for k in ('created', 'updated'))
        listed_text = code(0, 'issue', 'list').stdout
        assert 'contract-owner (agent wt-a), claimed' in listed_text, listed_text
        updated = as_json('issue', 'update', 'CON-3', '-t', 'third b', '--json')
        assert updated['key'] == 'CON-3' and updated['title'] == 'third b'
        nxt = as_json('issue', 'next', '--json')
        assert nxt['key'] == 'CON-3' and 'comments' in nxt and 'claim' in nxt
        # 1.0 fleet case 13: with --json, stdout is one JSON value and stderr
        # is empty, the claim included; --ready is accepted.
        claimed = code(0, 'issue', 'next', '--claim', '--json', '--ready')
        assert claimed.stderr == '', claimed.stderr
        assert json.loads(claimed.stdout)['claim']['holder'] == 'contract-owner', claimed.stdout
        text = code(0, 'issue', 'release', 'CON-3')
        assert text.stdout.startswith('Released CON-3'), text.stdout
        assert 'Capture stdout only' in code(0, 'issue', 'next', '--help').stdout
        # An assigned ready issue is not offered, and the refusal says so.
        code(0, 'issue', 'update', 'CON-3', '--assignee', 'contract-owner')
        empty = code(5, 'issue', 'next')
        assert '1 ready issue matches but is assigned (CON-3 to contract-owner)' in empty.stderr, empty.stderr
        unheld = code(4, 'issue', 'release', 'CON-3')
        assert "'lll issue update CON-3 --assignee none' offers it" in unheld.stderr, unheld.stderr
        code(0, 'issue', 'update', 'CON-3', '--assignee', '')
        assert as_json('issue', 'view', 'CON-3', '--json')['assignee'] == ''
        # A token is saved by logging in; config says how (case 14).
        refused = code(2, 'config', 'set', 'token', 'x')
        assert "lll login --token -" in refused.stderr, refused.stderr
        assert "lll login --token -" in code(0, 'config', '--help').stdout

        made = as_json('issue', 'comment', 'CON-3', '-b', 'json comment', '--json')
        assert made['body'] == 'json comment' and RFC3339.match(made['created']), made
        code(0, 'label', 'create', 'used')
        code(0, 'issue', 'update', 'CON-3', '--label', 'used')
        clean(code(4, 'label', 'delete', 'used'))

        # --- --raw names the holder (LLL-638) ---
        raw = code(0, 'issue', 'view', 'CON-2', '--raw').stdout
        assert '- **Claimed:** contract-owner (agent wt-a) (since ' in raw, raw
        # Unclaimed is said, not omitted (1.0 fleet, case 16).
        assert '- **Claimed:** none' in code(0, 'issue', 'view', 'CON-3', '--raw').stdout
        assert 'Claimed:   none' in code(0, 'issue', 'view', 'CON-3').stdout
        # A stale stamp's refusal prints the retry with the current stamp; it runs.
        stale = code(4, 'issue', 'update', 'CON-3', '-t', 'third r', '--if-unchanged-since', '2020-01-01T00:00:00.000Z')
        retry = [l for l in stale.stderr.splitlines() if 'retry with the current stamp: ' in l]
        assert retry, stale.stderr
        code(0, *shlex.split(retry[0].split('retry with the current stamp: ', 1)[1])[1:])
        assert as_json('issue', 'view', 'CON-3', '--json')['title'] == 'third r'
        refused = code(2, 'issue', 'update', 'CON-3', '--claim')
        assert 'to claim, run: lll issue claim CON-3' in refused.stderr and 'usage:' not in refused.stderr, refused.stderr

        # --- time flags take both forms and compare instants ---
        stamp = as_json('issue', 'view', 'CON-3', '--json')['updated']
        code(0, 'issue', 'update', 'CON-3', '-t', 'third c', '--if-unchanged-since', stamp)
        stamp = as_json('issue', 'view', 'CON-3', '--json')['updated']
        code(0, 'issue', 'update', 'CON-3', '-t', 'third d', '--if-unchanged-since', stamp.replace('T', ' '))
        clean(code(4, 'issue', 'update', 'CON-3', '-t', 'stale', '--if-unchanged-since', stamp))
        assert 'CON-3' in code(0, 'issue', 'list', '--since', stamp.replace('T', ' ')).stdout

        # --- lll api: exit 0 on any answer unless --fail ---
        code(0, 'api', 'GET', '/api/collections/issues/records/nope')
        missing = code(3, 'api', 'GET', '/api/collections/issues/records/nope', '--fail')
        assert '"status":404' in missing.stdout.replace(' ', ''), missing.stdout
        code(6, 'api', 'GET', '/api/collections/issues/records', '--fail', token_override='not.a.token')
    finally:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
print('cli contract: ok')
