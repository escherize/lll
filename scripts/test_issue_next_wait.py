#!/usr/bin/env python3
"""issue next --wait: block until an issue is ready, then offer it (LLL-820).

Runs against the isolated e2e service in a team of its own, so the agenda
holds only the issues created here. Each waiting case starts with nothing to
offer, starts the waiter, proves it is still running, then changes the board.
"""
import os
import subprocess
import sys
import time

binary, api = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='NXW')
env.pop('LLL_AGENT', None)


def invoke(*args, timeout=30):
    return subprocess.run([binary, *args], env=env, capture_output=True,
                          text=True, timeout=timeout)


def run(*args):
    result = invoke(*args)
    assert result.returncode == 0, (args, result.stderr)
    return result.stdout


def create(title, *extra):
    out = run('issue', 'create', title, '--json', *extra)
    import json
    return f"NXW-{json.loads(out)['number']}"


def waiter(*args):
    return subprocess.Popen([binary, 'issue', 'next', *args], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def still_waiting(proc, seconds=2.0):
    """The waiter must block: it has not exited after `seconds`."""
    time.sleep(seconds)
    assert proc.poll() is None, ('exited instead of waiting', proc.communicate())


def finish(proc, within=15):
    out, err = proc.communicate(timeout=within)
    return proc.returncode, out.strip(), err


def holder(key):
    import json
    claim = json.loads(run('issue', 'view', key, '--json')).get('claim')
    return (claim or {}).get('agent', None) if claim else None


run('team', 'create', '--key', 'NXW', '-n', 'Next wait')
run('project', 'create', '-n', 'Alpha')
for label in ('agent', 'hold'):
    run('label', 'create', '-n', label)

# Without --wait an empty agenda still exits 5 at once.
started = time.monotonic()
result = invoke('issue', 'next', '--claim', '--agent', 'w0')
assert result.returncode == 5 and not result.stdout, result
assert time.monotonic() - started < 5, 'plain next must not wait'

# A value without a unit, or not positive, is a usage error before any wait.
for bad in ('30', '0s', '-5s', 'soon'):
    result = invoke('issue', 'next', '--claim', '--wait', bad)
    assert result.returncode == 2 and not result.stdout, (bad, result)
    assert '--wait' in result.stderr, (bad, result.stderr)

# 1. Nothing ready for the whole wait: exit 5, no key, after about the wait.
started = time.monotonic()
result = invoke('issue', 'next', '--claim', '--agent', 'w0', '--wait', '3s')
elapsed = time.monotonic() - started
assert result.returncode == 5 and not result.stdout, result
assert 2.5 <= elapsed < 10, elapsed
assert 'waited 3s' in result.stderr, result.stderr

# 2. An issue created during the wait is claimed and printed.
proc = waiter('--claim', '--agent', 'w1', '--wait', '30s')
still_waiting(proc)
created = create('Made while a worker waits')
code, out, err = finish(proc)
assert (code, out) == (0, created), (code, out, err)
assert holder(created) == 'w1', holder(created)
run('issue', 'close', created, '--agent', 'w1')

# 3. An issue unblocked during the wait is claimed and printed. The blocker
# is held by another session, so it is not offerable itself.
blocker = create('Foundation')
run('issue', 'claim', blocker, '--agent', 'builder')
blocked = create('Needs the foundation')
run('issue', 'block', blocked, blocker)
proc = waiter('--claim', '--agent', 'w1', '--wait', '30s')
still_waiting(proc)
run('issue', 'close', blocker, '--agent', 'builder')
code, out, err = finish(proc)
assert (code, out) == (0, blocked), (code, out, err)
run('issue', 'close', blocked, '--agent', 'w1')

# 4. A released claim returns its issue to the waiter.
released = create('Handed back')
run('issue', 'claim', released, '--agent', 'builder')
proc = waiter('--claim', '--agent', 'w1', '--wait', '30s')
still_waiting(proc)
run('issue', 'release', released, '--agent', 'builder')
code, out, err = finish(proc)
assert (code, out) == (0, released), (code, out, err)
run('issue', 'close', released, '--agent', 'w1')

# 5. Two waiters, one new issue: exactly one gets the key and the claim. The
# other keeps waiting and exits 5 with no key when its wait ends.
first = waiter('--claim', '--agent', 'w1', '--wait', '8s')
second = waiter('--claim', '--agent', 'w2', '--wait', '8s')
still_waiting(first)
still_waiting(second, 0)
contested = create('One issue, two workers')
results = [finish(first, 20), finish(second, 20)]
winners = [r for r in results if r[0] == 0]
losers = [r for r in results if r[0] != 0]
assert len(winners) == 1 and len(losers) == 1, results
assert winners[0][1] == contested, results
assert losers[0][0] == 5 and losers[0][1] == '', results
assert holder(contested) in ('w1', 'w2'), holder(contested)
run('issue', 'close', contested, '--agent', holder(contested))

# 6. Filters apply to the wait. Each waiter must ignore a decoy that an
# unfiltered wait would take, then take the first issue that matches.
proc = waiter('--claim', '--agent', 'w1', '--wait', '30s', '--label', 'agent',
              '--exclude-label', 'hold')
still_waiting(proc)
decoys = [create('No label'), create('Held', '--label', 'agent', '--label', 'hold')]
still_waiting(proc)
wanted = create('Labelled', '--label', 'agent')
code, out, err = finish(proc)
assert (code, out) == (0, wanted), (code, out, err)
run('issue', 'close', wanted, '--agent', 'w1')

proc = waiter('--claim', '--agent', 'w1', '--wait', '30s', '--project', 'Alpha')
still_waiting(proc)  # the two decoys are ready, unclaimed and outside Alpha
in_project = create('Project work', '--project', 'Alpha')
code, out, err = finish(proc)
assert (code, out) == (0, in_project), (code, out, err)
run('issue', 'close', in_project, '--agent', 'w1')

# 7. With work already there, --wait returns at once.
started = time.monotonic()
result = invoke('issue', 'next', '--claim', '--agent', 'w1', '--wait', '30s')
assert result.returncode == 0 and result.stdout.strip() in decoys, result
assert time.monotonic() - started < 10, 'ready work must not wait'

# 8. An unknown name still fails before any wait.
started = time.monotonic()
result = invoke('issue', 'next', '--claim', '--wait', '30s', '--label', 'nope')
assert result.returncode != 0 and not result.stdout, result
assert "no label named 'nope'" in result.stderr, result.stderr
assert time.monotonic() - started < 10, 'a bad filter must not wait'

print('issue next --wait: timeout, created, unblocked, released, two waiters, filters and usage passed')
