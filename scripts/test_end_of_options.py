#!/usr/bin/env python3
"""End-of-options behavior through real command dispatch and team extraction."""
import json
import os
import subprocess
import sys

binary, api = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='EOO')


def run(*args, success=True):
    result = subprocess.run([binary, *args], env=env, text=True, capture_output=True, timeout=15)
    assert (result.returncode == 0) == success, result.stderr
    return result.stdout if success else result.stderr


run('team', 'create', '-k', 'EOO', '-n', 'End of options')
run('label', 'create', '--team', 'EOO', '--', '--team')
run('project', 'create', '--', '--help')
issue = json.loads(run('issue', 'create', '--json', '--team', 'EOO', '--', '--help'))
assert issue['title'] == '--help' and issue['expand']['team']['key'] == 'EOO'
key = f"EOO-{issue['number']}"
# A marker consumed as a value does not terminate later option parsing.
run('issue', 'update', key, '-d', '--', '--label', '--team', '--project', '--help')
record = json.loads(run('issue', 'view', key, '--json', '--'))
assert record['description'] == '--'
assert record['expand']['labels'][0]['name'] == '--team'
assert record['expand']['project']['name'] == '--help'
assert len(json.loads(run('issue', 'list', '--json', '--'))['items']) == 1
# Marker handling must not bypass arity, turn trailing flags into options,
# or allow missing required flags to reach a mutating handler.
run('issue', 'list', '--', '--json', success=False)
run('issue', 'create', '--', '--help', '--state=done', success=False)
run('team', 'create', '--', '--help', success=False)
assert json.loads(run('issue', 'view', key, '--json')) == record
assert len(json.loads(run('issue', 'list', '--json'))['items']) == 1
print('End of options: literal help/team values, named values, team extraction, arity and rejected writes passed')
