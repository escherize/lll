#!/usr/bin/env python3
"""issue next --project/--label/--exclude-label and the --claim --json packet (LLL-611).

Runs against the isolated e2e service in a team of its own, so the agenda
holds only the issues created here. Every filter has a decoy that ranks
higher and that the filter must skip.
"""
import json
import os
import subprocess
import sys

binary, api = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='NXT')


def invoke(*args):
    return subprocess.run([binary, *args], env=env, capture_output=True,
                          text=True, timeout=15)


def run(*args):
    result = invoke(*args)
    assert result.returncode == 0, (args, result.stderr)
    return result.stdout


def create(title, priority, *extra):
    record = json.loads(run('issue', 'create', title, '--json', '--priority', priority, *extra))
    return f"NXT-{record['number']}"


def chosen(args, key):
    out = run('issue', 'next', *args).strip()
    assert out == key, (args, out, key)


def refused(args, needle):
    result = invoke('issue', 'next', *args)
    assert result.returncode != 0 and not result.stdout, (args, result)
    assert needle in result.stderr, (args, result.stderr)


run('team', 'create', '--key', 'NXT', '-n', 'Next filters')
run('project', 'create', '-n', 'Alpha')
for label in ('agent', 'ops', 'hold'):
    run('label', 'create', '-n', label)

top = create('Urgent decoy, no project or label', 'urgent')
in_project = create('Project work', 'low', '--project', 'Alpha')
agent = create('Agent work', 'medium', '--label', 'agent')
ops = create('Ops work', 'low', '--label', 'ops')
held = create('Held agent work', 'high', '--label', 'agent', '--label', 'hold')

# Unfiltered, the urgent decoy wins; each filter must skip it.
chosen([], top)
chosen(['--project', 'Alpha'], in_project)
chosen(['--label', 'agent'], held)
chosen(['--label', 'agent', '--exclude-label', 'hold'], agent)
# Repeated --label is any-of: hold alone brings in the held issue, and once
# agent is excluded, ops still counts.
chosen(['--label', 'ops', '--label', 'hold'], held)
chosen(['--label', 'ops', '--label', 'hold', '--exclude-label', 'agent'], ops)
# Repeated --exclude-label skips an issue carrying any of them.
chosen(['--exclude-label', 'ops', '--exclude-label', 'hold', '--label', 'ops', '--label', 'agent'], agent)

# Unknown names fail before any fetch, naming the command that lists the real ones.
refused(['--project', 'Nope'], "no project named 'Nope' — see 'lll project list'")
refused(['--label', 'nope'], "no label named 'nope' — see 'lll label list'")
refused(['--exclude-label', 'nope'], "no label named 'nope' — see 'lll label list'")

# The packet: one call that claims and returns record, blockers and comments.
blocker = create('Finished foundation', 'none')
run('issue', 'close', blocker)
run('issue', 'block', agent, blocker)
run('issue', 'comment', agent, '-b', 'context for whoever takes this')
packet = json.loads(run('issue', 'next', '--label', 'agent', '--exclude-label', 'hold',
                        '--claim', '--json'))
assert f"NXT-{packet['number']}" == agent, packet
assert packet['expand']['assignee']['name'] == 'e2e-agent', packet
assert packet['claim']['holder'] == 'e2e-agent', packet
assert [c['body'] for c in packet['comments']] == ['context for whoever takes this'], packet
assert [f"NXT-{b['number']}" for b in packet['expand']['blocked_by']] == [blocker], packet
assert [l['name'] for l in packet['expand']['labels']] == ['agent'], packet
for field in ('docs', 'findings'):
    assert packet[field] == [], (field, packet)
# Same object `issue view --json` gives, so readers need one shape.
view = json.loads(run('issue', 'view', agent, '--json'))
assert sorted(view) == sorted(packet), (sorted(view), sorted(packet))
# Claimed now, so the filtered queue is empty and says so.
refused(['--label', 'agent', '--exclude-label', 'hold'], 'agenda is empty')
print('issue next filters: project, any-of labels, exclusions, unknown names and the claim packet passed')
