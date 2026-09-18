#!/usr/bin/env python3
"""GitHub import defaults and idempotency through the CLI and a local gh fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

binary, api = sys.argv[1:]
assert urlsplit(api).hostname in ('127.0.0.1', 'localhost'), api
fixture = [
    {'number': 11, 'title': 'Retry failed tasks', 'body': 'Keep retry history.',
     'state': 'OPEN', 'labels': [{'name': 'bug', 'color': 'd73a4a'}]},
    {'number': 12, 'title': 'Explain worker setup', 'body': 'Document each step.',
     'state': 'CLOSED', 'labels': []},
]

with tempfile.TemporaryDirectory(prefix='lll-gh-import-') as directory:
    root = Path(directory)
    gh = root / 'gh'
    gh.write_text('#!/usr/bin/env python3\nimport sys\n'
                  'assert sys.argv[1:3] == ["issue", "list"]\n'
                  f'print({json.dumps(fixture)!r})\n')
    gh.chmod(0o755)
    env = dict(os.environ, LLL_URL=api, LLL_CONFIG_HOME=str(root / 'config'),
               PATH=str(root) + os.pathsep + os.environ['PATH'])
    env.pop('LLL_ME', None)

    def cli(*args, team='GHEMOJI', check=True):
        result = subprocess.run([binary, *args], cwd=root,
                                env=dict(env, LLL_TEAM=team), text=True,
                                capture_output=True, timeout=30)
        if check:
            assert result.returncode == 0, (args, result.stderr)
        return result

    def issues(team='GHEMOJI'):
        return json.loads(cli('issue', 'list', '--json', team=team).stdout)['items']

    for team in ('GHEMOJI', 'GHPLAIN'):
        cli('team', 'create', '-k', team, '-n', team)
    cli('import', 'github', 'fixture/tasks', '--emoji', '🧪')
    first = issues()
    assert len(first) == 2
    assert all(i['emoji'] == '🧪' for i in first)
    assert {i['refs'] for i in first} == {'gh#11', 'gh#12'}
    assert {i['state'] for i in first} == {'todo', 'done'}
    assert any(i['labels'] for i in first)
    cli('import', 'github', 'fixture/tasks', '--emoji', '🐛')
    assert issues() == first, 'reimport changed existing records'
    cli('import', 'github', 'fixture/tasks', team='GHPLAIN')
    plain = issues('GHPLAIN')
    assert len(plain) == 2 and all(i['emoji'] == '' for i in plain)
    invalid = cli('import', 'github', 'fixture/tasks', '--emoji',
                  'this is not one emoji', team='GHPLAIN', check=False)
    assert invalid.returncode != 0 and '--emoji takes one emoji' in invalid.stderr
    assert issues('GHPLAIN') == plain, 'invalid default mutated records'

print('GitHub import: emoji default, omission, refs/states/labels, idempotency and invalid-default refusal passed')
