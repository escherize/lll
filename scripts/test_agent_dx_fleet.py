#!/usr/bin/env python3
"""Exercise fleet isolation and lifecycle before provisioning real workers.

With no arguments: the fast harness checks (no lll binary; part of e2e).
With --cases BINARY: every case's seed and judge against real scratch boards.
Worker 01 (pairs: workers 01+02) is a scripted correct worker that must pass;
worker 02 (pairs: 03+04) makes one plausible mistake and must fail with the
named reason. --dry-run makes every worker correct and prints the table.
"""
import argparse
import json
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from agent_dx_fleet import (CASES, audit_path, conn_file, connection, private_dir, private_write, public_snapshot,
                            publish_audit, serve, stop, wrapper_env)

HERE = Path(__file__).resolve().parent


def harness_checks():
    with tempfile.TemporaryDirectory(prefix='lll-fleet-harness-') as temporary:
        root = Path(temporary)
        worker = root / '01'
        private_dir(worker)
        assert worker.stat().st_mode & 0o777 == 0o700
        conn = worker / 'conn.txt'
        for text in ('http://127.0.0.1:1234\n', 'http://127.0.0.1:1234\nfake\n',
                     'https://hosted.invalid:1234\nfake\nFLEET\n'):
            private_write(conn, text)
            try:
                connection(conn)
            except ValueError:
                pass
            else:
                raise AssertionError('accepted partial or non-loopback connection')
        private_write(conn, 'http://127.0.0.1:1234\nthrowaway-test-token\nFLEET\n')
        assert conn.stat().st_mode & 0o777 == 0o600
        conn.chmod(0o644)
        private_write(conn, conn.read_text())
        assert conn.stat().st_mode & 0o777 == 0o600
        fake = root / 'fake-lll'
        fake.write_text('#!/usr/bin/env python3\nimport os\nfrom pathlib import Path\n'
                        'assert os.environ["LLL_URL"]=="http://127.0.0.1:1234"\n'
                        'assert os.environ["LLL_TOKEN"]=="throwaway-test-token"\n'
                        'assert os.environ["LLL_TEAM"]=="FLEET"\n'
                        'assert "LLL_POISON" not in os.environ and "XDG_POISON" not in os.environ\n'
                        'assert Path(os.environ["HOME"])==Path.cwd()/"home"\n'
                        'print("isolated wrapper: "+os.environ["LLL_TOKEN"])\n')
        fake.chmod(0o700)
        env = dict(os.environ, LLL_URL='https://hosted.invalid', LLL_TEAM='REAL',
                   LLL_TOKEN='not-real-controller-token', LLL_POISON='bad', XDG_POISON='bad')
        result = subprocess.run([sys.executable, str(HERE / 'agent_dx_fleet.py'),
                                 'wrapper', str(worker), str(fake), 'env', '--help'],
                                env=env, text=True, capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == 'isolated wrapper: [REDACTED]', (result.stdout, result.stderr)
        primary = audit_path(fake, worker)
        audit = json.loads(primary.read_text())
        assert audit['command'] == ['lll', '--help'] and audit['exit_code'] == 0
        assert 'throwaway-test-token' not in json.dumps(audit)
        assert not (worker / 'calls.jsonl').exists()
        (worker / 'calls.jsonl').write_text('malformed worker reconstruction')
        again = subprocess.run([sys.executable, str(HERE / 'agent_dx_fleet.py'),
                                'wrapper', str(worker), str(fake), 'env', 'throwaway-test-token'],
                               env=env, text=True, capture_output=True, timeout=10)
        assert again.returncode == 0, again.stderr
        assert primary.stat().st_mode & 0o777 == 0o600
        assert len(primary.read_text().splitlines()) == 2
        assert 'throwaway-test-token' not in primary.read_text()
        assert publish_audit(fake, worker)
        assert (worker / 'worker-supplied-calls.jsonl').read_text() == 'malformed worker reconstruction'
        assert (worker / 'calls.jsonl').read_bytes() == primary.read_bytes()
        assert publish_audit(fake, worker)
        # Wrapper modes: what each case's workers get from conn.txt and their own shell.
        worker = worker.resolve()
        hostile = {'LLL_URL': 'https://hosted.invalid', 'LLL_TOKEN': 'worker-set-token',
                   'LLL_TEAM': 'REAL', 'LLL_CONFIG_HOME': str(worker / 'colleague')}
        noteam, _ = wrapper_env(worker, 'noteam', hostile)
        assert noteam['LLL_TOKEN'] == 'throwaway-test-token' and 'LLL_TEAM' not in noteam
        config, _ = wrapper_env(worker, 'config', hostile)
        assert not {'LLL_URL', 'LLL_TOKEN', 'LLL_TEAM'} & set(config)
        assert config['LLL_CONFIG_HOME'] == str(worker / 'home' / 'config')
        override, hidden = wrapper_env(worker, 'override', hostile)
        assert override['LLL_URL'] == 'http://127.0.0.1:1234' and override['LLL_TOKEN'] == 'worker-set-token'
        assert override['LLL_CONFIG_HOME'] == str(worker / 'colleague') and 'worker-set-token' in hidden
        own_home, _ = wrapper_env(worker, 'override', {'LLL_CONFIG_HOME': str(worker / 'colleague')})
        assert 'LLL_TOKEN' not in own_home, 'a worker config home must not be overridden by conn.txt'
        plain, _ = wrapper_env(worker, 'env', hostile)
        assert plain['LLL_TOKEN'] == 'throwaway-test-token' and plain['LLL_CONFIG_HOME'] == str(worker / 'home' / 'config')
        try:
            wrapper_env(worker, 'override', {'LLL_CONFIG_HOME': str(root)})
        except SystemExit:
            pass
        else:
            raise AssertionError('override accepted a config home outside the worker directory')
        from agent_dx_fleet import foreign_url, redact
        board = 'http://127.0.0.1:1234'
        assert foreign_url(['member', 'invite', 'x', '--url', 'https://elsewhere.invalid'], board)
        assert foreign_url(['login', '--url=https://elsewhere.invalid'], board)
        assert foreign_url(['config', 'set', 'url', 'http://127.0.0.1:9'], board)
        assert not foreign_url(['config', 'set', 'url', board + '/'], board)
        assert not foreign_url(['issue', 'list'], board)
        assert 'C4BHS4' not in redact('  temporary password: C4BHS4YE2PXQP22GF6F2CV5TLP\n')
        assert 'hunter2' not in redact('lll login --email a@b.c --password hunter2')
        snapshot = {'webhooks': [{'id': 'hook', 'secret': 'throwaway-hook-secret'}]}
        assert public_snapshot(snapshot)['webhooks'][0]['secret'] == '[REDACTED]'
        assert snapshot['webhooks'][0]['secret'] == 'throwaway-hook-secret'
        run_root = root / 'fresh-run'

        def commands():
            (run_root / 'case-01-run-1').mkdir()
            yield '{"action":"provision","case":"01","run":1}\n'
        args = SimpleNamespace(root=run_root, binary=fake, commit='fixture',
                               sha256=hashlib.sha256(fake.read_bytes()).hexdigest())
        with patch('sys.stdin', commands()), patch('sys.stdout', io.StringIO()), \
             patch('agent_dx_fleet.Board', side_effect=AssertionError('launched into reused path')):
            try:
                serve(args)
            except AssertionError as error:
                assert str(error) == 'case/run paths must be fresh', error
            else:
                raise AssertionError('accepted reused case/run path')
        exited = subprocess.Popen([sys.executable, '-c', 'pass'])
        exited.wait(timeout=5)
        exited.terminate = lambda: (_ for _ in ()).throw(AssertionError('re-signaled reaped child'))
        stop(exited)
        resistant = subprocess.Popen([sys.executable, '-c',
            'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(60)'], stdout=subprocess.PIPE, text=True)
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            assert resistant.stdout.readline().strip() == 'ready'
            stop(resistant)
            assert resistant.returncode is not None and unrelated.poll() is None
        finally:
            stop(resistant)
            stop(unrelated)
    assert sorted(CASES) == [f'{n:02}' for n in range(1, 21)]
    rules = HERE.parent / 'docs' / 'agent-dx-fleet' / 'rules'
    assert sorted(p.name for p in rules.glob('*.md')) == sorted(f'{k}-{c["slug"]}.md' for k, c in CASES.items())
    print('Fleet harness: incomplete/foreign connections refused; private files; poisoned environment cleared; '
          'wrapper modes scoped; foreign URLs refused; audited/redacted calls and passwords; owned resistant child reaped without signaling '
          'unrelated or reaped children; twenty cases each with a rules file.')


# Scripted workers. Each drives the real wrapper exactly as a worker would.

class Worker:
    def __init__(self, info):
        self.number, self.dir, self.wrapper = info['number'], Path(info['directory']), info['wrapper']

    def run(self, *args, stdin=None, env=None, check=True):
        result = subprocess.run([self.wrapper, *args], cwd=self.dir, input=stdin, text=True,
                                capture_output=True, timeout=60, env=dict(os.environ, **(env or {})))
        if check and result.returncode != 0:
            raise AssertionError(f'worker {self.number}: lll {" ".join(args)} exited {result.returncode}: {result.stderr}')
        return result

    def json(self, *args, **kw):
        return json.loads(self.run(*args, **kw).stdout)

    def key(self, search):
        return self.json('issue', 'list', '--search', search, '--json')['items'][0]['key']

    def report(self, answer=None, **extra):
        body = {'done': True, 'invocations': 0, 'failures': [], 'guesses': [], 'papercuts': [],
                'api_thoughts': '', 'report': 'scripted', **extra}
        if answer is not None:
            body['answer'] = answer
        (self.dir / 'report.json').write_text(json.dumps(body))
        (self.dir / 'report.md').write_text('scripted\n')

    def poll(self, key, needle, seconds=30):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if needle(self.json('issue', 'view', key, '--json')):
                return
            time.sleep(0.5)
        raise AssertionError(f'worker {self.number}: timed out waiting on {key}')


def bodies(issue):
    return [c['body'] for c in issue.get('comments') or []]


def w01(w, right):
    key = w.key('Retry loses' if right else 'keyboard')
    w.run('issue', 'comment', key, '-b', f'fleet-01-{w.number}: A socket reset made the retry skip the comment; '
          'preserve one comment and report the saved result.')
    w.report()


def w02(w, right):
    states = ['--state', 'backlog', '--state', 'todo', '--state', 'in-progress', '--state', 'in-review'] if right else []
    out = w.run('issue', 'list', '--project', 'Checkout', '--label', 'bug', *states, '--json').stdout
    (w.dir / f'fleet-02-{w.number}.json').write_text(out)
    keys = [i['key'] for i in json.loads(out)['items']]
    w.report({'keys': keys, 'count': len(keys)})


def w03(w, right):
    found = w.json('finding', 'near', 'src/retry/backoff.lis' if right else 'src/cache', '--json')['items']
    slug = found[0]['slug']
    w.report({'slug': slug, 'confidence': w.json('doc', 'view', slug, '--json')['confidence']})


def w04(w, right):
    who = w.json('whoami', '--json')
    picked = w.run('issue', 'next', *([] if right else ['--claim'])).stdout.strip()
    w.report({'identity': who['name'], 'team': who['team'], 'next': picked, 'nothing_to_do_exit': 5})


def w05(w, right):
    slugs = [d['slug'] for d in w.json('doc', 'list', '-k', 'decision', '--json')['items']]
    slug = 'pagination-cursor' if right else 'retry-once'
    body = w.run('doc', 'view', slug, '--raw').stdout
    w.report({'decision_slugs': slugs, 'slug': slug, 'restatement': body.split('.')[0]})


def w06(w, right):
    w.run('issue', 'create', '-t', f'Repair flaky upload retry (worker {w.number})', '-b', 'Retry a dropped upload once '
          'and preserve the saved attachment.', '--state', 'todo', '--priority', '2', '--project', 'Fleet sandbox',
          *(['--label', 'bug'] if right else []))
    w.report()


def w07(w, right):
    key = w.key('Flush the export')
    w.run('issue', 'claim', key)
    w.run('issue', 'comment', key, '-b', f'fleet-07-{w.number}: flushed the export queue; closing.')
    w.run('issue', 'close', key, *([] if right else ['--keep-claim']))
    w.report()


def w08(w, right):
    slug = f'fleet-08-{w.number}-upload-lock'
    w.run('finding', 'create', slug, '-t', f'Upload retry holds the cache lock (worker {w.number})', '-a', 'storage',
          '--paths', 'src/upload,src/retry', '-b', 'The retry path takes the cache lock before the upload finishes.',
          '--confidence', 'suspected')
    if right:
        w.run('finding', 'confirm', slug)
    w.report()


def w09(w, right):
    w.run('label', 'edit', 'regresion', '-n', 'regression')
    w.run('project', 'create', f'Stabilize {w.number}')
    for title in ('upload', 'login') + (() if right else ('search',)):
        w.run('issue', 'update', w.key(f'Fix flaky {title}'), '--project', f'Stabilize {w.number}')
    w.report()


def w10(w, right):
    key = w.key('progress bar')
    line = f'fleet-10-{w.number}: reopened after the regression came back.'
    if right:
        w.run('issue', 'update', key, '--description-replace', 'keep the cache warm=flush the cache first',
              '--description-append', line, '--state', 'todo')
    else:
        w.run('issue', 'update', key, '-b', line, '--state', 'todo')
    w.report()


def w11(w, right):
    parent = w.key('Ship offline mode')
    for part in ('cache schema', 'sync queue', 'conflict banner'):
        child = w.json('issue', 'create', '-t', f'Offline mode: {part} (worker {w.number})', '--priority', '1', '--json')
        if right:
            w.run('issue', 'block', parent, child['key'])
    w.report({'next': w.run('issue', 'next').stdout.strip()})


def w12(w, right):
    refused = w.run('issue', 'create', '-t', f'fleet-12-{w.number} rollout checklist', check=False)
    assert refused.returncode != 0, 'issue create without a team succeeded'
    w.run('issue', 'create', '-t', f'fleet-12-{w.number} rollout checklist', '--label', 'bug',
          '--team', 'OPS' if right else 'FLEET')
    w.run('issue', 'create', '-t', f'fleet-12-{w.number} rollout notes', '--label', 'bug', '--team', 'FLEET')
    w.report({'no_team_exit': refused.returncode})


def w13(w, right):
    script = w.dir / f'fleet-13-{w.number}.sh'
    auth = '' if right else f'export LLL_TOKEN={connection(conn_file(w.dir))[1]}\n'
    script.write_text(f'#!/bin/sh\n{auth}cd "$(dirname "$0")"\nwhile true; do\n'
                      '  key=$(./lll issue next --label sweep --claim); code=$?\n'
                      '  [ "$code" -eq 5 ] && exit 0\n  [ "$code" -ne 0 ] && exit "$code"\n'
                      '  ./lll issue close "$key" || exit $?\ndone\n')
    script.chmod(0o700)
    result = subprocess.run(['sh', str(script)], cwd=w.dir, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    w.report()


def w14(w, right):
    assert w.run('whoami', check=False).returncode != 0
    url, token, _ = connection(conn_file(w.dir))
    w.run('config', 'set', 'url', url)
    assert w.run('whoami', check=False).returncode == 6
    if right:
        w.run('login', '--token', '-', stdin=token + '\n')
        w.run('whoami')
    w.report()


def w15(w, right):
    name = f'bot-helper-{w.number}'
    old, new = w.dir / f'helper-{w.number}.env', w.dir / f'helper-{w.number}-rotated.env'
    old.write_text(w.run('bot', 'create', name, '--env').stdout)

    def as_helper(path):
        token = next(l.split('=', 1)[1].strip('\'"') for l in path.read_text().splitlines() if 'LLL_TOKEN=' in l)
        return w.run('whoami', env={'LLL_TOKEN': token}, check=False)
    assert as_helper(old).returncode == 0
    if right:
        new.write_text(w.run('bot', 'rotate', name, '--env').stdout)
        assert as_helper(old).returncode == 6
        assert as_helper(new).returncode == 0
    else:
        new.write_text(old.read_text())
    w.report()


def w16(a, b, right):
    key = a.key('Migrate the upload worker')
    a.run('issue', 'claim', key)
    a.run('issue', 'comment', key, '-b', f'fleet-16-{a.number}: handing off to bot-fleet-worker-{b.number}; the queue drain is next.')
    if right:
        a.run('issue', 'release', key)
        b.poll(key, lambda i: not i.get('claim') and any(t.startswith(f'fleet-16-{a.number}') for t in bodies(i)))
        b.run('issue', 'claim', key)
    b.run('issue', 'comment', key, '-b', f'fleet-16-{b.number}: picked up from bot-fleet-worker-{a.number}.')
    a.report()
    b.report()


def w17(a, b, right):
    key = a.key('Shared release notes')

    def append(w, role):
        w.run('issue', 'update', key, '--description-append', f'fleet-17-{w.number}: role {role} checked the upload path.')
    if right:
        threads = [threading.Thread(target=append, args=(w, r)) for w, r in ((a, 'A'), (b, 'B'))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    else:
        append(a, 'A')
        b.run('issue', 'update', key, '-b', f'Release notes:\nfleet-17-{b.number}: role B checked the upload path.')
    a.report()
    b.report()


def w18(a, b, right):
    key = a.key('Watch handshake')
    log, err = a.dir / f'fleet-18-{a.number}-watch.jsonl', a.dir / f'fleet-18-{a.number}-watch.err'
    watcher = None
    if right:
        with log.open('w') as out, err.open('w') as errs:
            watcher = subprocess.Popen([a.wrapper, 'watch', '--json'], cwd=a.dir, stdout=out, stderr=errs)
        deadline = time.time() + 20
        while 'watch: ready' not in err.read_text():
            assert time.time() < deadline, 'watch never became ready'
            time.sleep(0.2)
    a.run('issue', 'comment', key, '-b', f'fleet-18-{a.number}: watching')
    b.poll(key, lambda i: f'fleet-18-{a.number}: watching' in bodies(i))
    created = b.json('issue', 'create', '-t', f'fleet-18-{b.number} live event', '--priority', '3', '--json')['key']
    b.run('issue', 'update', created, '--priority', '2')
    b.run('issue', 'comment', key, '-b', f'fleet-18-{b.number}: done {created}')
    a.poll(key, lambda i: f'fleet-18-{b.number}: done {created}' in bodies(i))
    seen = []
    if watcher:
        deadline = time.time() + 10
        while len(log.read_text().splitlines()) < 2 and time.time() < deadline:
            time.sleep(0.2)
        watcher.terminate()
        watcher.wait(timeout=10)
        events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        seen = sorted({f'FLEET-{int(e["record"]["number"])}' for e in events})
    a.report({'partner_keys': seen})
    b.report()


def w19(w, right):
    name, email = f'colleague-{w.number}', f'colleague-{w.number}@example.com'
    printed = w.run('member', 'invite', name, '--email', email, *(['--team', 'FLEET'] if right else [])).stdout
    password = re.search(r'temporary password: (\S+)', printed).group(1)
    home = {'LLL_CONFIG_HOME': str(w.dir / 'colleague')}
    w.run('login', '--email', email, '--password', password, env=home)
    teams = [t['key'] for t in w.json('team', 'list', '--json', env=home)['items']]
    w.report({'colleague_teams': teams})


def w20(w, right):
    key = w.key('Upload retry flakes')
    w.run('issue', 'move', key, 'in-review', check=False)
    if right:
        w.run('issue', 'update', key, '--state', 'in-review')
    w.run('issue', 'comment', key, '-b', f'fleet-20-{w.number}: ready for a second pair of eyes.')
    w.report(error_rating={'command': 'lll issue move', 'rating': 3, 'why': 'scripted'})


SCRIPTED = {f'{n:02}': fn for n, fn in enumerate(
    [w01, w02, w03, w04, w05, w06, w07, w08, w09, w10, w11, w12, w13, w14, w15, w16, w17, w18, w19, w20], 1)}
# The reason each wrong worker must fail with: a substring of one judge error.
WRONG_REASON = {
    '01': 'comment issue', '02': 'answer keys', '03': 'answer slug', '04': 'new claims',
    '05': 'answer slug', '06': 'issue labels', '07': 'still claimed', '08': 'finding confidence',
    '09': 'unexpected change to issues', '10': 'issue description', '11': 'blocked_by', '12': 'wrong team',
    '13': 'hard-codes a token', '14': 'does not authenticate', '15': 'rotated token equals', '16': 'claim holder',
    '17': 'line appears 0 times', '18': 'lacks the partner create', '19': 'colleague scope', '20': 'issue state',
}


class Controller:
    def __init__(self, binary, root):
        digest = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
        self.proc = subprocess.Popen([sys.executable, str(HERE / 'agent_dx_fleet.py'), '--root', str(root),
                                      '--binary', str(binary), '--commit', 'fleet-test', '--sha256', digest],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert self.read()['ready']

    def read(self):
        line = self.proc.stdout.readline()
        assert line, f'controller exited ({self.proc.wait()})'
        return json.loads(line)

    def send(self, **command):
        self.proc.stdin.write(json.dumps(command) + '\n')
        self.proc.stdin.flush()
        return self.read()


def run_cases(binary, cases, dry_run):
    table = []
    with tempfile.TemporaryDirectory(prefix='lll-fleet-cases-') as temporary:
        controller = Controller(binary, Path(temporary) / 'run')
        try:
            for case in cases:
                pair = CASES[case]['pair']
                started = time.time()
                provisioned = controller.send(action='provision', case=case, workers=4 if pair else 2)
                workers = [Worker(info) for info in provisioned['workers']]
                groups = [workers[i:i + 2] for i in range(0, len(workers), 2)] if pair else [[w] for w in workers]
                for index, group in enumerate(groups):
                    SCRIPTED[case](*group, dry_run or index == 0)
                judged = controller.send(action='judge')
                stopped = controller.send(action='stop')
                assert stopped['stopped'] and stopped['listeners_gone'] == 2 * len(groups), stopped
                for index, board in enumerate(judged['boards']):
                    right = dry_run or index == 0
                    table.append((case, CASES[case]['slug'], '+'.join(board['workers']),
                                  'correct' if right else 'wrong', 'pass' if board['pass'] else 'fail',
                                  '; '.join(board['errors'])))
                    if right:
                        assert board['pass'], f'case {case} correct worker failed: {board["errors"]}'
                    else:
                        assert not board['pass'], f'case {case} wrong worker passed'
                        assert any(WRONG_REASON[case] in e for e in board['errors']), \
                            f'case {case} wrong worker failed for another reason: {board["errors"]}'
                print(f'case {case} ok ({time.time() - started:.1f}s)', flush=True)
            controller.send(action='exit')
        finally:
            if controller.proc.poll() is None:
                controller.proc.stdin.close()
                controller.proc.wait(timeout=60)
    print('| case | slug | workers | worker | judge | reasons |')
    print('|---|---|---|---|---|---|')
    for case, slug, workers, kind, verdict, reasons in table:
        print(f'| {case} | {slug} | {workers} | {kind} | {verdict} | {reasons} |')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, metavar='BINARY', help='run every case against this lll binary')
    parser.add_argument('--only', nargs='*', default=sorted(CASES))
    parser.add_argument('--dry-run', action='store_true', help='every worker correct; all must pass')
    options = parser.parse_args()
    harness_checks()
    if options.cases:
        run_cases(options.cases.resolve(), options.only, options.dry_run)
