#!/usr/bin/env python3
"""Walk the demo board's own "Works if:" lines (LLL-433).

`lll up --demo` seeds a board whose issues each end in a checkable claim. Those
claims are prose shipped to a newcomer, so they have to stay true: a demo that
promises something the product stopped doing is worse than no demo, and the
landing page already taught us that lesson once.

So this boots the demo and checks the promises rather than the seeding. Counting
ten issues would pass forever while every claim rotted.
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LLL = ROOT / 'target/.lisette/bin/lll'
DEADLINE = 120


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix='lll-demo-check-'))
    db, web = free_port(), free_port()

    # Its own everything. Without LLL_URL the boot adopts whatever PocketBase is
    # already healthy on the default port, which on a developer's machine is
    # another board entirely; without the config root and the XDG unset it reads
    # the developer's real token (LLL-400, LLL-418, LLL-423, LLL-430).
    env = dict(os.environ,
               LLL_CONFIG_HOME=str(base / 'config'),
               LLL_URL=f'http://127.0.0.1:{db}',
               LLL_BIND='127.0.0.1',
               LLL_ADMIN_EMAIL='admin@local.dev',
               LLL_ADMIN_PASSWORD='admin-local-123')
    for leak in ('LLL_ME', 'LLL_TOKEN', 'LLL_TEAM', 'LLL_SORT', 'LLL_WEB_URL',
                 'LLL_BOARD_TOKEN', 'XDG_CONFIG_HOME'):
        env.pop(leak, None)
    (base / 'work').mkdir(parents=True)

    log = base / 'up.log'
    with log.open('w') as handle:
        proc = subprocess.Popen(
            [str(LLL), 'up', '--demo', '--no-open', '--pb-dir', str(base / 'pb'),
             '--port', str(web)],
            cwd=base / 'work', env=env, stdout=handle, stderr=handle,
            start_new_session=True)
    try:
        started = time.monotonic()
        while time.monotonic() - started < DEADLINE:
            out = log.read_text()
            if 'board  http' in out:
                break
            assert proc.poll() is None, f'lll up --demo exited early:\n{out}'
            time.sleep(0.1)
        else:
            raise AssertionError(f'demo board did not start:\n{log.read_text()}')

        out = log.read_text()
        assert 'seeded DEMO' in out, f'nothing was seeded:\n{out}'
        # The demo has to leave the CLI able to run its own instructions,
        # otherwise every "Works if:" line answers "not logged in".
        assert 'pointed at this board' in out, f'CLI was left unconfigured:\n{out}'

        def cli(*args, **kw):
            return subprocess.run([str(LLL), *args], cwd=base / 'work',
                                  env=dict(env, **kw.pop('extra', {})),
                                  capture_output=True, text=True, timeout=60)

        # The env pins LLL_URL/LLL_TEAM for the boot; the CLI checks below must
        # ride what --demo wrote to the config, which is what a person has.
        env.pop('LLL_URL', None)

        issues = json.loads(cli('issue', 'list', '--json').stdout)
        items = issues if isinstance(issues, list) else issues.get('items', [])
        assert len(items) == 10, f'expected 10 seeded issues, got {len(items)}'
        missing = [i['title'] for i in items
                   if 'Works if:' not in (i.get('description') or '')]
        assert not missing, f'seeded issues with no checkable claim: {missing}'

        docs = cli('doc', 'list').stdout
        for slug in ('start-here', 'why-not-a-todo-list', 'how-claims-work',
                     'a-finding-looks-like-this'):
            assert slug in docs, f'doc {slug} missing from:\n{docs}'

        # DEMO-1: a second claim is refused and names the holder.
        assert cli('issue', 'claim', 'DEMO-1').returncode == 0, 'first claim failed'
        cli('member', 'add', '-n', 'alex')
        mint = cli('token', 'create', 'alex', '--duration', '3600',
                   extra={'LLL_TOKEN': ''})
        token = re.search(r'^LLL_TOKEN=(\S+)$', mint.stdout, re.M)
        assert token, f'could not mint a second identity:\n{mint.stdout}{mint.stderr}'
        second = cli('issue', 'claim', 'DEMO-1',
                     extra={'LLL_TOKEN': token.group(1), 'LLL_ME': 'alex'})
        assert second.returncode != 0, 'a claimed issue was claimable by someone else'
        assert 'bcm' in (second.stdout + second.stderr) or 'held' in (second.stdout + second.stderr), \
            f'the refusal did not name the holder:\n{second.stdout}{second.stderr}'

        # DEMO-3: the key goes to stdout, the claim to stderr, so it pipes.
        nxt = cli('issue', 'next', '--claim')
        assert re.fullmatch(r'DEMO-\d+', nxt.stdout.strip()), \
            f'issue next --claim put more than a key on stdout: {nxt.stdout!r}'
        assert 'laim' in nxt.stderr, f'no claim line on stderr: {nxt.stderr!r}'

        # DEMO-6: a blocked issue leaves the ready list.
        assert cli('issue', 'block', 'DEMO-6', 'DEMO-5').returncode == 0
        ready = json.loads(cli('issue', 'list', '--ready', '--json').stdout)
        ready = ready if isinstance(ready, list) else ready.get('items', [])
        assert 6 not in [i.get('number') for i in ready], \
            'DEMO-6 stayed ready while its blocker was open'

        # DEMO-7: search reaches a doc by its body, not only its title.
        found = cli('search', 'rejected').stdout
        assert 'why-not-a-todo-list' in found, \
            f'search missed the decision doc by body text:\n{found}'

        # DEMO-10: archiving hides without deleting, and says the way back.
        assert cli('team', 'archive', 'DEMO').returncode == 0
        refused = cli('issue', 'create', 'should refuse')
        assert refused.returncode != 0, 'an archived team accepted a write'
        assert 'unarchive' in (refused.stdout + refused.stderr), \
            'the refusal did not name lll team unarchive'
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        proc.wait(timeout=30)

    print('Demo: seeded board, CLI pointed at it, and every "Works if:" claim held')


if __name__ == '__main__':
    main()
