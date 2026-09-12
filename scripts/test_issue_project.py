#!/usr/bin/env python3
"""Exercise project edits through the CLI against the isolated e2e service."""
import json
import os
import subprocess
import sys

binary, api = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='ENG')


def invoke(*args):
    return subprocess.run([binary, *args], env=env, capture_output=True,
                          text=True, timeout=15)


def run(*args):
    result = invoke(*args)
    assert result.returncode == 0, result.stderr
    return result.stdout


help_text = run('issue', 'update', '--help')
assert 'project name (see \'lll project list\'); pass "" to clear it' in help_text
# A real name must remain addressable, including the conventional display word.
run('project', 'create', '-n', 'none')
issue = json.loads(run('issue', 'create', 'Project clear probe', '--json',
                      '--project', 'none', '--label', 'chore', '--priority', 'high',
                      '--description', 'Keep this description', '--emoji', '🧪'))
key = f"ENG-{issue['number']}"
run('issue', 'claim', key)
run('issue', 'comment', key, '-b', 'Keep this comment and claim')


def view():
    return json.loads(run('issue', 'view', key, '--json'))


def without_project(record):
    # Only the relation, its expansion and the server timestamp may change.
    record = dict(record)
    for field in ('project', 'updated'):
        record.pop(field, None)
    record['expand'] = dict(record['expand'])
    record['expand'].pop('project', None)
    return record


before = view()
assert before['expand']['project']['name'] == 'none'
assert before['claim'] and before['comments'] and before['labels']
for spelling in [('--project', ''), ('--project=',)]:
    output = run('issue', 'update', key, *spelling)
    assert 'project=none' in output
    after = view()
    assert after['project'] == ''
    assert without_project(after) == without_project(before)
    # Clearing an already empty relation is safe, too.
    run('issue', 'update', key, *spelling)
    assert without_project(view()) == without_project(before)
    run('issue', 'update', key, '--project', 'none')
    assert view()['project'] == before['project']

# Omission keeps the project; an unresolved name must not partially save edits.
run('issue', 'update', key, '--description', 'Changed description')
assert view()['project'] == before['project']
before_invalid = view()
result = invoke('issue', 'update', key, '--project', 'missing-project-350',
                '--title', 'Must not save')
assert result.returncode != 0 and 'no project named' in result.stderr
assert view() == before_invalid
result = invoke('issue', 'update', key, '--project')
assert result.returncode != 0
assert view() == before_invalid
print('Project edits: empty and equals clear, omission preserves, literal none resolves, unrelated fields survive')
