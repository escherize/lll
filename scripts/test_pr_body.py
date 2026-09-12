#!/usr/bin/env python3
"""Exercise PR body transport with a real issue API and a recording gh."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

binary, api = sys.argv[1:]
binary = str(Path(binary).resolve())
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    gh = root / 'gh'
    gh.write_text(f'#!{sys.executable}\n' + '''import json,os,pathlib,sys
pathlib.Path(os.environ['PR_CAPTURE']).write_text(json.dumps({'args':sys.argv[1:],'body':sys.stdin.read()}))
print('https://github.example/test/pull/1')
sys.exit(int(os.environ.get('PR_EXIT', '0')))
''')
    gh.chmod(0o755)
    capture = root / 'capture.json'
    env = dict(os.environ, HOME=directory, LLL_URL=api, LLL_TEAM='ENG',
               LLL_WEB_URL='https://board.example', PR_CAPTURE=str(capture),
               PATH=directory + os.pathsep + os.environ['PATH'])

    def run(*args, body=None, extra=None):
        return subprocess.run([binary, *args], input=body, env=dict(env, **(extra or {})),
                              cwd=directory, capture_output=True, text=True, timeout=20)

    # The 40k emoji body exceeds Linux's single-argument byte ceiling while
    # staying below the PR character limit. The marker must remain literal.
    for description in ('', 'Quotes " and $() `literal`\n\nline two', '🧪' * 40000, 'x' * 100000):
        created = run('issue', 'create', 'PR body fixture', '-d', '-', '--json', body=description)
        assert created.returncode == 0, created.stderr
        record = json.loads(created.stdout)
        key = f'ENG-{record["number"]}'
        result = run('issue', 'pr', key)
        assert result.returncode == 0, result.stderr
        payload = json.loads(capture.read_text())
        assert payload['args'] == ['pr', 'create', '--title', f'{key}: PR body fixture', '--body-file', '-'], payload['args']
        link = f'https://board.example/issue/{key}'
        expected = link + ('\n\n' + description if description else '')
        if len(expected) <= 65536:
            assert payload['body'] == expected
            assert 'exceeds' not in result.stderr
        else:
            assert payload['body'].startswith(link + '\n\n')
            assert 'full description' in payload['body']
            assert len(payload['body']) <= 65536
            assert 'linking to the full description' in result.stderr
        assert 'https://github.example/test/pull/1' in result.stdout

    failed = run('issue', 'pr', key, extra={'PR_EXIT': '7'})
    assert failed.returncode != 0 and 'gh pr create' in failed.stderr, failed
print('PR bodies: exact stdin transport, large Unicode, oversized link fallback and gh failure passed')
