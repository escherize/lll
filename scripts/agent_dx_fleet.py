#!/usr/bin/env python3
"""Own isolated lll fleet instances and judge artifacts independently over REST.

Cases are numbered 01-20 as in the fleet plan. Each case names a seed (the
fixtures its board needs beyond the shared base), a judge (ground truth read
over REST, plus worker files where the artifact is a file) and the wrapper
mode its workers get. Pair cases put two workers on one board; the odd worker
is role A, the even worker role B.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

from board_startup import wait_for_endpoints
from real_config_guard import refuse_real_config

COLLECTIONS = ('teams', 'members', 'labels', 'projects', 'issues', 'comments',
               'docs', 'claims', 'views', 'favorites', 'webhooks', 'invites', 'issue_counters')
TARGET_TITLE = 'Retry loses the issue comment'
TARGET_BODY = 'A socket reset caused the retry to skip the comment. Preserve one comment and report the saved result.'
CREATE_BODY = 'Retry a dropped upload once and preserve the saved attachment.'
BOT_SECONDS = 6 * 3600
# Wrapper modes. env: url, token and team from conn.txt. noteam: url and token
# only. config: nothing from conn.txt, the CLI reads the worker's HOME config.
# override: like env, but a worker-set LLL_TOKEN or LLL_CONFIG_HOME (inside the
# worker directory) wins, so a worker can act as a second identity. The URL is
# always conn.txt's: no inherited setting overrides it, and the wrapper refuses
# a --url or `config set url` naming any other server, in every mode.
MODES = ('env', 'noteam', 'config', 'override')


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def private_write(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'w') as output:
        os.fchmod(output.fileno(), 0o600)
        output.truncate(0)
        output.write(text)


def connection(path):
    lines = path.read_text().splitlines()
    if len(lines) != 3 or not all(lines):
        raise ValueError('connection needs URL, token and team')
    url = urllib.parse.urlsplit(lines[0])
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.path:
        raise ValueError('connection must use an explicit loopback listener')
    if lines[2] != 'FLEET':
        raise ValueError('unexpected fleet team')
    return lines


def clean_env(home):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(home), LLL_CONFIG_HOME=str(home / 'config'),
               XDG_CONFIG_HOME=str(home / 'config'), LC_ALL='C')
    refuse_real_config(env, 'agent_dx_fleet')
    return env


JWT = r'[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}'


def redact(text, values=(), help_page=False):
    for value in values:
        if value:
            text = text.replace(value, '[REDACTED]')
    text = re.sub(JWT, '[REDACTED JWT]', text)
    # A help page names the flag with placeholder prose ("--password pw");
    # redacting it garbled login --help for a case 19 worker.
    if not help_page:
        text = re.sub(r'(temporary password: |--old-password |--password[ =])\S+', r'\1[REDACTED]', text)
    return re.sub(r'board_token=[^\s&]+', 'board_token=[REDACTED]', text)


def stop(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
    else:
        child.wait()


def public_snapshot(snapshot):
    result = json.loads(json.dumps(snapshot))
    for webhook in result.get('webhooks', []):
        if 'secret' in webhook:
            webhook['secret'] = '[REDACTED]'
    return result


def audit_path(binary, worker):
    return binary.parent / 'audits' / worker.parent.name / (worker.name + '.jsonl')


def read_audit(binary, worker):
    path = audit_path(binary, worker)
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def publish_audit(binary, worker):
    source = audit_path(binary, worker)
    for line in source.read_text().splitlines():
        entry = json.loads(line)
        assert set(entry) == {'command', 'exit_code', 'stdout', 'stderr'}
        assert isinstance(entry['command'], list)
    destination = worker / 'calls.jsonl'
    supplied = worker / 'worker-supplied-calls.jsonl'
    if destination.exists() and destination.read_bytes() != source.read_bytes():
        assert not supplied.exists(), 'audit evidence changed again after publication'
        destination.rename(supplied)
    shutil.copy2(source, destination)
    return supplied.exists()


def conn_file(worker):
    """Where a worker's connection facts live. Only case 14, whose task is to
    repair a config by hand, keeps them in the worker's own directory; every
    other case keeps them beside it, so a worker cannot read its token by
    opening a file it sees (cases 01-05 run 1: 1-2 of 10 workers per case
    opened conn.txt despite the rule)."""
    inside = worker / 'conn.txt'
    return inside if inside.exists() else worker.parent / '.conn' / f'{worker.name}.txt'


def wrapper_env(worker, mode, inherited):
    """The child environment for one wrapped call, and the secrets to redact."""
    url, token, team = connection(conn_file(worker))
    env = clean_env(worker / 'home')
    if mode in ('env', 'noteam', 'override'):
        env.update(LLL_URL=url, LLL_TOKEN=token)
    if mode in ('env', 'override'):
        env['LLL_TEAM'] = team
    secrets_seen = [token]
    if mode == 'override':
        own_home = inherited.get('LLL_CONFIG_HOME', '')
        if own_home:
            resolved = Path(own_home).resolve()
            if resolved != worker and worker not in resolved.parents:
                raise SystemExit('fleet wrapper: LLL_CONFIG_HOME must be inside your worker directory')
            env['LLL_CONFIG_HOME'] = env['XDG_CONFIG_HOME'] = str(resolved)
            env.pop('LLL_TOKEN')
        if inherited.get('LLL_TOKEN'):
            env['LLL_TOKEN'] = inherited['LLL_TOKEN']
            secrets_seen.append(inherited['LLL_TOKEN'])
    env['LLL_AGENT'] = 'codex'
    refuse_real_config(env, 'agent_dx_fleet')
    return env, secrets_seen


def wrapper_main():
    worker = Path(sys.argv[2]).resolve()
    binary = Path(sys.argv[3]).resolve()
    mode = sys.argv[4]
    assert mode in MODES, 'unknown wrapper mode'
    env, hidden = wrapper_env(worker, mode, os.environ)
    args = sys.argv[5:]
    hidden += [value for flag, value in zip(args, args[1:]) if flag in ('--password', '--old-password', '--admin-password')]
    if foreign_url(args, connection(conn_file(worker))[0]):
        raise SystemExit('fleet wrapper: this board is the only server; --url and `config set url` must name conn.txt line 1')
    # Only a minted credential on stdout reaches the worker unredacted, in override
    # mode: `bot create|rotate --env > helper.env` (case 15) and the temporary
    # password of `member invite` (case 19) are what the worker must receive.
    minted = mode == 'override' and (args[:1] == ['bot'] and '--env' in args or args[:2] == ['member', 'invite'])
    # Streams, so `lll watch` in the background writes as it goes; a signal to
    # this process (kill %1, ^C) reaches the CLI and the call is still audited.
    # When the caller merged the streams (`2>&1`: fds 1 and 2 are one file),
    # give the CLI one pipe for both so their order is exactly the binary's.
    # Two pipes pumped by two threads reordered them (case 13 rerun).
    merged = os.path.sameopenfile(1, 2)
    child = subprocess.Popen([str(binary), *args], cwd=worker, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merged else subprocess.PIPE)
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda sig, _frame: child.send_signal(sig))
    captured = {'stdout': [], 'stderr': []}

    # The audit is always redacted.
    help_page = '--help' in args or '-h' in args or args[:1] == ['help']

    def pump(source, sink, name):
        for chunk in iter(source.readline, b''):
            text = chunk.decode(errors='replace')
            line = redact(text, hidden, help_page)
            captured[name].append(line)
            sink.write(text if minted and name == 'stdout' else line)
            sink.flush()

    pumps = [threading.Thread(target=pump, args=(child.stdout, sys.stdout, 'stdout'))]
    if not merged:
        pumps.append(threading.Thread(target=pump, args=(child.stderr, sys.stderr, 'stderr')))
    for thread in pumps:
        thread.start()
    code = child.wait()
    for thread in pumps:
        thread.join()
    code = 128 - code if code < 0 else code
    entry = {'command': ['lll', *[redact(arg, hidden) for arg in args]], 'exit_code': code,
             'stdout': ''.join(captured['stdout']), 'stderr': ''.join(captured['stderr'])}
    audit = audit_path(binary, worker)
    private_dir(audit.parent)
    fd = os.open(audit, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a') as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(json.dumps(entry) + '\n')
    raise SystemExit(code)


def foreign_url(args, url):
    """Whether a call names a server other than the board (--url X, config set url X)."""
    named = [value for flag, value in zip(args, args[1:]) if flag == '--url']
    named += [a.removeprefix('--url=') for a in args if a.startswith('--url=')]
    if args[:3] == ['config', 'set', 'url'] and len(args) > 3:
        named.append(args[3])
    return any(value.rstrip('/') != url for value in named)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class Seat:
    """One worker on a board: its directory, number, identity and wrapper.

    A worker acts as a bot, except where a case needs a person: a bot cannot
    own a bot, so case 15's worker is the person who creates one."""

    def __init__(self, worker, number, person=False):
        self.worker, self.number, self.person = worker, number, person
        self.name = f'fleet-worker-{number}' if person else f'bot-fleet-worker-{number}'
        self.role = 'A' if int(number) % 2 else 'B'

    def report(self):
        try:
            data = json.loads((self.worker / 'report.json').read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def answer(self):
        report = self.report()
        answer = report.get('answer') if report else None
        return answer if isinstance(answer, dict) else {}


class Board:
    """One owned lll server, its base fixtures, one or two seats and a case seed."""

    def __init__(self, binary, controller, case, seats):
        self.binary, self.case, self.seats = binary, case, seats
        self.private = controller / seats[0].number
        private_dir(self.private)
        for seat in seats:
            private_dir(seat.worker)
            private_dir(seat.worker / 'home')
        self.child = None
        self.log = self.private / 'up.log'
        self.admin_token = ''
        self.fixtures = {}
        env = clean_env(self.private / 'home')
        private_dir(self.private / 'home')
        password = secrets.token_urlsafe(30)
        with socket.socket() as db, socket.socket() as web:
            db.bind(('127.0.0.1', 0))
            web.bind(('127.0.0.1', 0))
            db_port, web_port = db.getsockname()[1], web.getsockname()[1]
        env.update(LLL_URL=f'http://127.0.0.1:{db_port}', LLL_TEAM='FLEET',
                   LLL_BIND='127.0.0.1', USER='fleet-controller',
                   LLL_ADMIN_EMAIL='controller@example.invalid',
                   LLL_ADMIN_PASSWORD=password, LLL_BOARD_TOKEN=secrets.token_urlsafe(30))
        with self.log.open('w') as output:
            self.child = subprocess.Popen([str(binary), 'up', '--no-open', '--port', str(web_port),
                                           '--pb-dir', str(self.private / 'data')],
                                          cwd=self.private, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            endpoint = wait_for_endpoints(self.log)
            assert self.child.poll() is None, 'owned child exited'
            self.api, self.board = endpoint['db_url'], endpoint['board_url']
            self.admin_token = self.request('/api/collections/_superusers/auth-with-password',
                                           {'identity': env['LLL_ADMIN_EMAIL'], 'password': password}, auth=False)['token']
            self.person = next(m for m in self.records('members') if m['name'] == 'fleet-controller')
            self.person_token = self.request('/api/collections/members/impersonate/' + self.person['id'],
                                             {'duration': BOT_SECONDS})['token']
            for seat in seats:
                self.mint(seat)
            self.seed_base()
            CASES[case]['seed'](self)
            self.before = self.snapshot()
            for seat in seats:
                self.hand_over(seat)
            private_write(self.private / 'receipt.json', json.dumps({
                'case': case, 'seats': {s.number: s.member_id for s in seats}, 'fixtures': self.fixtures,
                'before': self.before}, indent=2))
        except BaseException:
            self.close()
            raise

    def mint(self, seat):
        if seat.person:
            member = self.create('members', {'name': seat.name, 'email': f'{seat.name}@example.invalid',
                                             'password': (pw := secrets.token_urlsafe(30)), 'passwordConfirm': pw,
                                             'kind': 'person', 'scope': 'all', 'mode': 'rw'})
            seat.token = self.request('/api/collections/members/impersonate/' + member['id'],
                                      {'duration': BOT_SECONDS})['token']
        else:
            mint_env = clean_env(self.private / 'home')
            mint_env.update(LLL_URL=self.api, LLL_TOKEN=self.person_token, LLL_TEAM='FLEET')
            mint = subprocess.run([str(self.binary), 'bot', 'create', seat.name, '--duration', str(BOT_SECONDS), '--env'],
                                  cwd=self.private, env=mint_env, text=True, capture_output=True, timeout=20)
            assert mint.returncode == 0, redact(mint.stderr + mint.stdout)
            token = next(line.removeprefix('export LLL_TOKEN=') for line in mint.stdout.splitlines()
                         if line.startswith('export LLL_TOKEN='))
            seat.token = token.strip('\'"')
            member = self.member(seat.name)
            assert member['kind'] == 'bot' and member['owner'] == self.person['id']
        seat.member_id = member['id']
        assert self.token_identity(seat.token) == member['id'], 'worker handshake identity mismatch'

    def hand_over(self, seat):
        audit = audit_path(self.binary, seat.worker)
        private_dir(audit.parent)
        private_write(audit, '')
        private_dir(seat.worker.parent / '.conn')
        target = seat.worker.parent / '.conn' / f'{seat.worker.name}.txt'
        private_write(target, f'{self.api}\n{seat.token}\nFLEET\n')
        assert connection(conn_file(seat.worker))[0] == self.api
        script = self.binary.parent / 'harness' / 'agent_dx_fleet.py'
        mode = CASES[self.case]['mode']
        wrapper = (f'#!/usr/bin/env python3\nimport os\nos.execv({sys.executable!r}, [{sys.executable!r}, '
                   f'{str(script)!r}, "wrapper", {str(seat.worker)!r}, {str(self.binary)!r}, {mode!r}, *os.sys.argv[1:]])\n')
        (seat.worker / 'lll').write_text(wrapper)
        (seat.worker / 'lll').chmod(0o700)
        if self.case == '14':
            # Case 14 needs the right url and a valid token as inputs. Helpers
            # print them so no worker opens a credentials file (run 1: the
            # sandbox refused `sed -n 2p conn.txt` for one worker).
            for name, line in (('fleet-url', 1), ('fleet-token', 2)):
                helper = seat.worker / name
                helper.write_text(f'#!/bin/sh\nsed -n {line}p {str(target)!r}\n')
                helper.chmod(0o700)

    def close(self):
        if self.child:
            stop(self.child)
        for seat in self.seats:
            (seat.worker / 'conn.txt').unlink(missing_ok=True)
            (seat.worker.parent / '.conn' / f'{seat.worker.name}.txt').unlink(missing_ok=True)

    # REST

    def request(self, path, body=None, token=None, auth=True, method=None):
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['Authorization'] = 'Bearer ' + (token or self.admin_token)
        req = urllib.request.Request(self.api + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            hidden = [self.admin_token, getattr(self, 'person_token', '')] + [getattr(s, 'token', '') for s in self.seats]
            detail = redact(error.read().decode(), hidden)
            raise RuntimeError(f'controller REST {error.code} {path}: {detail}') from None

    def records(self, collection, token=None):
        rows = []
        page = 1
        while True:
            data = self.request(f'/api/collections/{collection}/records?perPage=200&page={page}&sort=id', token=token)
            rows.extend(data['items'])
            if page >= data['totalPages']:
                return rows
            page += 1

    def create(self, collection, body):
        return self.request(f'/api/collections/{collection}/records', body)

    def snapshot(self):
        return {name: self.records(name) for name in COLLECTIONS}

    def member(self, name):
        return next(m for m in self.records('members') if m['name'] == name)

    def token_identity(self, token):
        """The member id a token authenticates as, or None when the server refuses it."""
        try:
            return self.request('/api/collections/members/auth-refresh', {}, token=token)['record']['id']
        except RuntimeError:
            return None

    def cli(self, token, *args):
        env = clean_env(self.private / 'home')
        env.update(LLL_URL=self.api, LLL_TOKEN=token, LLL_TEAM='FLEET')
        return subprocess.run([str(self.binary), *args], cwd=self.private, env=env,
                              text=True, capture_output=True, timeout=20)

    # Fixtures

    def seed_base(self):
        self.team = next(t for t in self.records('teams') if t['key'] == 'FLEET')['id']
        self.bug = self.label('bug')
        self.label('docs')
        self.project = self.create('projects', {'team': self.team, 'name': 'Fleet sandbox', 'status': 'planned'})['id']
        self.target = self.issue(TARGET_TITLE, TARGET_BODY, priority=2)['id']
        self.decoys = [self.issue(title, body)['id'] for title, body in
                       [('Add keyboard shortcuts', 'Use the palette to move between issues.'),
                        ('Import decisions', 'Preserve the decision document links.')]]
        self.doc('retry-once', 'Retry once', 'decision',
                 'Retry once after inspecting the saved result. Rejected: unbounded blind retries create duplicates.')
        self.fixtures.update(team=self.team, bug=self.bug, project=self.project, target=self.target)

    def label(self, name, team=None):
        return self.create('labels', {'team': team or self.team, 'name': name})['id']

    def issue(self, title, body='', state='todo', priority=3, team=None, **fields):
        record = self.create('issues', {'team': team or self.team, 'title': title, 'description': body,
                                        'state': state, 'priority': priority, 'creator': self.person['id'], **fields})
        return self.request(f'/api/collections/issues/records/{record["id"]}')

    def doc(self, slug, title, kind, body, **fields):
        return self.create('docs', {'team': self.team, 'slug': slug, 'title': title, 'kind': kind, 'body': body, **fields})

    def key(self, issue_id, after):
        row = next(i for i in after['issues'] if i['id'] == issue_id)
        team = next(t for t in after['teams'] if t['id'] == row['team'])
        return f'{team["key"]}-{int(row["number"])}'

    # Judging

    def judge(self):
        after = self.snapshot()
        changes = diff(self.before, after)
        errors = CASES[self.case]['judge'](self, changes, after)
        # A report must never carry a credential (case 14 run 2: four pasted
        # full tokens). JWTs start with eyJ; any 100+ char run of one counts.
        for seat in self.seats:
            for name in ('report.md', 'report.json'):
                path = seat.worker / name
                if path.exists() and re.search(r'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}', path.read_text(errors='replace')):
                    errors.append(f'{name} of worker {seat.number} contains a token')
        numbers = [s.number for s in self.seats]
        supplied = {s.number: publish_audit(self.binary, s.worker) for s in self.seats}
        result = {'workers': numbers, 'pass': not errors, 'errors': errors,
                  'new_records': {name: len(c['added']) for name, c in changes.items() if c['added']},
                  'worker_supplied_audit_preserved': supplied}
        if self.case == '20':
            result['error_rating_present'] = {s.number: bool((s.report() or {}).get('error_rating')) for s in self.seats}
        for seat in self.seats:
            (seat.worker / 'truth.json').write_text(json.dumps(result, indent=2))
            (seat.worker / 'before.json').write_text(redact(json.dumps(public_snapshot(self.before), indent=2)))
            (seat.worker / 'after.json').write_text(redact(json.dumps(public_snapshot(after), indent=2)))
        return result


def diff(before, after):
    """Per collection: records added, records removed, and changed fields by id."""
    result = {}
    for name in COLLECTIONS:
        old = {row['id']: row for row in before[name]}
        new = {row['id']: row for row in after[name]}
        result[name] = {
            'added': [new[k] for k in new if k not in old],
            'removed': [old[k] for k in old if k not in new],
            'changed': {k: {f for f in set(old[k]) | set(new[k]) if old[k].get(f) != new[k].get(f)}
                        for k in old if k in new and old[k] != new[k]},
        }
    return result


def untouched(changes, added=None, changed=None):
    """Errors for every change outside the case's allowance: nothing else touched.

    added maps a collection to the exact count of new records; changed maps a
    collection to {record id: fields that may change}. Deletions never pass."""
    errors = []
    for name in COLLECTIONS:
        if name == 'issue_counters':
            if changes[name]['changed'] and not (added or {}).get('issues'):
                errors.append('issue counter moved: an issue was created (and maybe deleted)')
            continue
        want, got = (added or {}).get(name, 0), len(changes[name]['added'])
        if got != want:
            errors.append(f'expected {want} new {name} record(s), got {got}')
        for row in changes[name]['removed']:
            errors.append(f'{name} record {row["id"]} was deleted')
        allowed = (changed or {}).get(name, {})
        for key, fields in changes[name]['changed'].items():
            extra = fields - {'updated'} - allowed.get(key, set())
            if key not in allowed:
                extra = fields
            if extra:
                errors.append(f'unexpected change to {name} {key}: {sorted(extra)}')
    return errors


def expect(errors, record, what, **fields):
    for name, value in fields.items():
        if record.get(name) != value:
            errors.append(f'{what} {name}: expected {value!r}, got {record.get(name)!r}')


def one_added(changes, collection):
    """The single new record, or {} (untouched already named a wrong count)."""
    rows = changes[collection]['added']
    return rows[0] if len(rows) == 1 else {}


def row(after, collection, record_id):
    return next(r for r in after[collection] if r['id'] == record_id)


def called(board, seat, *words, code=0, also=()):
    """Whether the seat's audit holds `lll WORDS... [also...]` exiting with code."""
    return any(e['command'][1:1 + len(words)] == list(words) and e['exit_code'] == code
               and all(a in e['command'] for a in also) for e in read_audit(board.binary, seat.worker))


def answer_errors(seat, **expected):
    answer = seat.answer()
    if not answer:
        return [f'worker {seat.number}: report.json has no answer object']
    errors = []
    for name, value in expected.items():
        got = answer.get(name)
        if isinstance(value, set) and isinstance(got, list) and all(isinstance(g, str) for g in got):
            got = set(got)
        if got != value:
            errors.append(f'worker {seat.number}: answer {name}: expected {sorted(value) if isinstance(value, set) else value!r}, got {answer.get(name)!r}')
    return errors


# Cases. A seed adds fixtures to the base board; a judge returns exact reasons.

def seed_none(board):
    pass


def judge_01(board, changes, after):
    seat = board.seats[0]
    errors = untouched(changes, added={'comments': 1})
    comment = one_added(changes, 'comments')
    if comment:
        expect(errors, comment, 'comment', issue=board.target, author=seat.member_id,
               body=f'fleet-01-{seat.number}: A socket reset made the retry skip the comment; preserve one comment and report the saved result.')
    return errors


def seed_02(board):
    checkout = board.create('projects', {'team': board.team, 'name': 'Checkout', 'status': 'started'})['id']
    chore = board.label('chore')
    rows = [('Checkout total rounds down', 'todo', [board.bug], checkout, True),
            ('Checkout button double-submits', 'in-progress', [board.bug], checkout, True),
            ('Checkout retries the card twice', 'backlog', [board.bug], checkout, True),
            ('Checkout copy typo', 'todo', [chore], checkout, False),
            ('Checkout crash on empty cart', 'done', [board.bug], checkout, False),
            ('Checkout tax rounding', 'cancelled', [board.bug], checkout, False),
            ('Search crash on empty query', 'todo', [board.bug], '', False)]
    board.fixtures['export'] = [board.issue(t, state=s, labels=l, project=p)['id'] for t, s, l, p, hit in rows if hit]
    for t, s, l, p, hit in rows:
        if not hit:
            board.issue(t, state=s, labels=l, project=p)
    # Another team with the same label and project names: dropping --team
    # FLEET exports a superset (case 02 run 1 review, workers 05 and 09).
    shop = board.create('teams', {'key': 'SHOP', 'name': 'Storefront'})['id']
    shop_checkout = board.create('projects', {'team': shop, 'name': 'Checkout', 'status': 'started'})['id']
    board.issue('Checkout coupon field ignores paste', state='todo', team=shop,
                labels=[board.label('bug', team=shop)], project=shop_checkout)


def judge_02(board, changes, after):
    seat = board.seats[0]
    keys = {board.key(i, after) for i in board.fixtures['export']}
    errors = untouched(changes) + answer_errors(seat, keys=keys, count=len(keys))
    path = seat.worker / f'fleet-02-{seat.number}.json'
    try:
        exported = json.loads(path.read_text())
        items = exported.get('items') if isinstance(exported, dict) else exported
        got = {item.get('key') for item in items} if isinstance(items, list) else None
    except (OSError, ValueError, AttributeError):
        got = None
    if got != keys:
        errors.append(f'{path.name}: expected `issue list --json` output holding exactly {sorted(keys)}, got {sorted(got) if got else got!r}')
    return errors


def seed_03(board):
    board.label('storage')
    for slug, title, area, paths, confidence in [
            ('upload-retry-lock', 'Upload retry holds the cache lock', 'storage', 'src/upload,src/retry', 'suspected'),
            ('cache-eviction-order', 'Cache evicts the newest entry first', 'storage', 'src/cache', 'confirmed'),
            ('upload-quota', 'Upload quota counts retries twice', 'billing', 'src/billing/upload_quota.lis', 'confirmed'),
            ('palette-focus', 'Palette loses focus after search', 'ui', 'web/static', 'confirmed')]:
        board.doc(slug, title, 'finding', f'{title}.', area=area, paths=paths, confidence=confidence)


def judge_03(board, changes, after):
    return untouched(changes) + answer_errors(board.seats[0], slug='upload-retry-lock', confidence='suspected')


def seed_04(board):
    board.issue('Ship the offline mode', 'Blocked until shortcuts land.', priority=1, blocked_by=[board.decoys[0]])
    board.fixtures['next'] = board.issue('Rotate the staging certificate', 'It expires this week.', priority=1)['id']


def judge_04(board, changes, after):
    seat = board.seats[0]
    truth = board.key(board.fixtures['next'], after)
    return untouched(changes) + answer_errors(seat, identity=seat.name, team='FLEET', next=truth,
                                              nothing_to_do_exit=5)


def seed_05(board):
    board.doc('pagination-cursor', 'Paginate with cursors', 'decision',
              'Use opaque cursors for list pagination. Rejected: page numbers, because rows inserted mid-scan shift every later page.')
    board.doc('onboarding', 'Onboarding', 'wiki', 'Read the decisions before changing list endpoints.')
    board.doc('offline-mode', 'Offline mode', 'prd', 'Pagination must keep working offline.')


def judge_05(board, changes, after):
    seat = board.seats[0]
    errors = untouched(changes) + answer_errors(seat, slug='pagination-cursor',
                                                decision_slugs={'pagination-cursor', 'retry-once'})
    if 'cursor' not in str(seat.answer().get('restatement', '')).lower():
        errors.append(f'worker {seat.number}: answer restatement does not mention cursors')
    return errors


def judge_06(board, changes, after):
    seat = board.seats[0]
    errors = untouched(changes, added={'issues': 1})
    issue = one_added(changes, 'issues')
    if issue:
        expect(errors, issue, 'issue', team=board.team, creator=seat.member_id, state='todo', priority=2,
               title=f'Repair flaky upload retry (worker {seat.number})', description=CREATE_BODY,
               labels=[board.bug], project=board.project)
    return errors


def seed_07(board):
    board.fixtures['issue'] = board.issue('Flush the export queue', 'The queue holds stale exports.', priority=2)['id']


def judge_07(board, changes, after):
    seat, issue = board.seats[0], board.fixtures['issue']
    errors = untouched(changes, added={'comments': 1}, changed={'issues': {issue: {'state', 'assignee'}}})
    expect(errors, row(after, 'issues', issue), 'issue', state='done', assignee=seat.member_id)
    if any(c['issue'] == issue for c in after['claims']):
        errors.append('issue is still claimed after close')
    if not called(board, seat, 'issue', 'claim'):
        errors.append('no successful `issue claim` in the audit')
    comment = one_added(changes, 'comments')
    if comment:
        expect(errors, comment, 'comment', issue=issue, author=seat.member_id,
               body=f'fleet-07-{seat.number}: flushed the export queue; closing.')
    return errors


def seed_08(board):
    board.label('storage')


def judge_08(board, changes, after):
    seat = board.seats[0]
    errors = untouched(changes, added={'docs': 1})
    doc = one_added(changes, 'docs')
    if doc:
        expect(errors, doc, 'finding', team=board.team, kind='finding', slug=f'fleet-08-{seat.number}-upload-lock',
               title=f'Upload retry holds the cache lock (worker {seat.number})', area='storage',
               body='The retry path takes the cache lock before the upload finishes.',
               confidence='confirmed', author=seat.member_id)
        # Filing suspected may go through `finding create` or `doc create -k
        # finding` (both take --confidence since fleet-fixes-1); confirming
        # through `finding confirm` or `doc edit --confidence confirmed`.
        filed = called(board, seat, 'finding', 'create', also=('suspected',)) or \
            called(board, seat, 'doc', 'create', also=('finding', 'suspected'))
        confirmed = called(board, seat, 'finding', 'confirm') or \
            called(board, seat, 'doc', 'edit', also=('confirmed',))
        if not (filed and confirmed):
            errors.append('audit lacks a suspected finding filed and then confirmed')
        if {p.strip() for p in doc.get('paths', '').split(',')} != {'src/upload', 'src/retry'}:
            errors.append(f'finding paths: expected src/upload and src/retry, got {doc.get("paths")!r}')
    return errors


def seed_09(board):
    typo = board.label('regresion')
    board.fixtures['typo'] = typo
    board.fixtures['move'] = [board.issue(t, labels=[typo])['id'] for t in ('Fix flaky upload test', 'Fix flaky login test')]
    board.issue('Fix flaky search test', labels=[typo])


def judge_09(board, changes, after):
    seat, moved = board.seats[0], board.fixtures['move']
    errors = untouched(changes, added={'projects': 1},
                       changed={'labels': {board.fixtures['typo']: {'name'}}, 'issues': {i: {'project'} for i in moved}})
    expect(errors, row(after, 'labels', board.fixtures['typo']), 'label', name='regression')
    project = one_added(changes, 'projects')
    if project:
        expect(errors, project, 'project', name=f'Stabilize {seat.number}', team=board.team)
        for issue in moved:
            expect(errors, row(after, 'issues', issue), f'issue {board.key(issue, after)}', project=project['id'])
    return errors


REOPEN_BODY = 'Steps:\nretry the upload.\nkeep the cache warm.'


def seed_10(board):
    board.fixtures['issue'] = board.issue('Upload retry drops the progress bar', REOPEN_BODY, state='done')['id']


def judge_10(board, changes, after):
    seat, issue = board.seats[0], board.fixtures['issue']
    errors = untouched(changes, changed={'issues': {issue: {'description', 'state'}}})
    body = REOPEN_BODY.replace('keep the cache warm', 'flush the cache first') + \
        f'\nfleet-10-{seat.number}: reopened after the regression came back.'
    expect(errors, row(after, 'issues', issue), 'issue', state='todo', description=body)
    return errors


OFFLINE_PARTS = ('cache schema', 'sync queue', 'conflict banner')


def seed_11(board):
    board.fixtures['parent'] = board.issue(f'Ship offline mode (worker {board.seats[0].number})',
                                           'Too big for one change.', priority=1)['id']


def judge_11(board, changes, after):
    seat, parent = board.seats[0], board.fixtures['parent']
    errors = untouched(changes, added={'issues': 3}, changed={'issues': {parent: {'blocked_by'}}})
    titles = {f'Offline mode: {part} (worker {seat.number})' for part in OFFLINE_PARTS}
    parts = changes['issues']['added']
    if {i['title'] for i in parts} != titles:
        errors.append(f'blocker titles: expected {sorted(titles)}, got {sorted(i["title"] for i in parts)}')
    for issue in parts:
        expect(errors, issue, f'blocker {issue["title"]!r}', creator=seat.member_id, priority=1, team=board.team)
    if set(row(after, 'issues', parent)['blocked_by']) != {i['id'] for i in parts}:
        errors.append('parent blocked_by is not exactly the three new issues')
    keys = {board.key(i['id'], after) for i in parts}
    picked = board.cli(seat.token, 'issue', 'next').stdout.strip()
    if picked not in keys:
        errors.append(f'issue next now offers {picked!r}, not one of the blockers')
    answered = seat.answer().get('next')
    if answered not in keys:
        errors.append(f'worker {seat.number}: answer next {answered!r} is not one of the blockers {sorted(keys)}')
    return errors


def seed_12(board):
    board.fixtures['ops'] = ops = board.create('teams', {'key': 'OPS', 'name': 'Operations'})['id']
    board.fixtures['ops_bug'] = board.label('bug', team=ops)


def judge_12(board, changes, after):
    seat = board.seats[0]
    errors = untouched(changes, added={'issues': 2})
    wanted = {board.fixtures['ops']: f'fleet-12-{seat.number} rollout checklist',
              board.team: f'fleet-12-{seat.number} rollout notes'}
    labels = {l['id']: l for l in after['labels']}
    for issue in changes['issues']['added']:
        if wanted.get(issue['team']) != issue['title']:
            errors.append(f'issue {issue["title"]!r} landed in the wrong team')
        expect(errors, issue, f'issue {issue["title"]!r}', creator=seat.member_id)
        names = [labels[l]['name'] for l in issue['labels'] if l in labels]
        if names != ['bug'] or any(labels[l]['team'] != issue['team'] for l in issue['labels']):
            errors.append(f'issue {issue["title"]!r} must carry its own team\'s bug label')
    if sorted(i['team'] for i in changes['issues']['added']) != sorted(wanted):
        errors.append('expected exactly one new issue in each of OPS and FLEET')
    refused = [e for e in read_audit(board.binary, seat.worker)
               if e['command'][1:3] == ['issue', 'create'] and e['exit_code'] != 0
               and not any(a.startswith('--team') for a in e['command'])]
    answered = seat.answer().get('no_team_exit')
    if not refused:
        errors.append('no refused `issue create` without --team in the audit')
    elif type(answered) is not int or answered != refused[0]['exit_code']:
        errors.append(f'worker {seat.number}: answer no_team_exit {seat.answer().get("no_team_exit")!r} '
                      f'does not match the observed exit {refused[0]["exit_code"]}')
    return errors


SWEEP_TITLES = ('Sweep: prune stale branches', 'Sweep: rotate logs', 'Sweep: delete old previews')


def seed_13(board):
    sweep = board.label('sweep')
    board.fixtures['sweep'] = [board.issue(t, labels=[sweep])['id'] for t in SWEEP_TITLES]
    board.fixtures['blocked'] = board.issue('Sweep: drop the legacy table', labels=[sweep],
                                            blocked_by=[board.decoys[0]])['id']
    # Rehearsal issues: workers test --claim parsing here, never on sweep
    # (case 13 rerun: four rehearsed on the real sweep issues).
    practice = board.label('practice')
    board.fixtures['practice'] = [board.issue(f'Practice: dry run {n}', labels=[practice])['id'] for n in (1, 2, 3)]


def judge_13(board, changes, after):
    seat, ready = board.seats[0], board.fixtures['sweep']
    practice = set(board.fixtures['practice'])
    allowed = {i: {'state', 'assignee'} for i in ready}
    allowed.update({i: {'state', 'assignee', 'description', 'priority'} for i in practice})
    claims = changes['claims']
    changes = dict(changes, claims={'added': [r for r in claims['added'] if r.get('issue') not in practice],
                                    'removed': [r for r in claims['removed'] if r.get('issue') not in practice],
                                    'changed': claims['changed']})
    errors = untouched(changes, changed={'issues': allowed})
    for issue in ready:
        expect(errors, row(after, 'issues', issue), f'issue {board.key(issue, after)}', state='done')
    if [c for c in after['claims'] if c.get('issue') not in practice]:
        errors.append('claims remain after the sweep')
    script = seat.worker / f'fleet-13-{seat.number}.sh'
    if not script.is_file():
        return errors + [f'{script.name} is missing']
    text = script.read_text()
    if seat.token in text or re.search(JWT, text) or re.search(r'LLL_TOKEN\s*=', text):
        errors.append(f'{script.name} hard-codes a token')
    if 'conn.txt' in text:
        errors.append(f'{script.name} reads conn.txt; the wrapper supplies the connection')
    for issue in ready:
        expect(errors, row(after, 'issues', issue), f'issue {board.key(issue, after)}', assignee=seat.member_id)
    if 'issue next' not in text or '5' not in text:
        errors.append(f'{script.name} does not drive `issue next` and test exit 5')
    nexts = [e for e in read_audit(board.binary, seat.worker) if e['command'][1:3] == ['issue', 'next']]
    if not nexts or nexts[-1]['exit_code'] != 5:
        errors.append('the last `issue next` in the audit did not exit 5')
    return errors


def seed_14(board):
    seat = board.seats[0]
    expired = board.request('/api/collections/members/impersonate/' + seat.member_id, {'duration': 1})['token']
    config = seat.worker / 'home' / 'config' / 'lll'
    private_dir(seat.worker / 'home' / 'config')
    private_dir(config)
    private_write(config / 'lll.toml', f'url = "http://127.0.0.1:{free_port()}"\ntoken = "{expired}"\nteam = "FLEET"\n')
    time.sleep(2)
    assert board.token_identity(expired) is None, 'seeded token did not expire'


def judge_14(board, changes, after):
    seat = board.seats[0]
    errors = untouched(changes)
    try:
        config = tomllib.loads((seat.worker / 'home' / 'config' / 'lll' / 'lll.toml').read_text())
    except (OSError, ValueError) as error:
        return errors + [f'saved config unreadable: {error}']
    if config.get('url') != board.api:
        errors.append('saved config url is not the board API')
    if board.token_identity(config.get('token', '')) != seat.member_id:
        errors.append('saved config token does not authenticate as the worker bot')
    if config.get('team', 'FLEET') != 'FLEET':
        errors.append('saved config team changed')
    whoami = [e for e in read_audit(board.binary, seat.worker) if e['command'][1:2] == ['whoami']]
    if not whoami or whoami[-1]['exit_code'] != 0:
        errors.append('the last `whoami` in the audit did not succeed')
    if not any(e['exit_code'] != 0 for e in whoami):
        errors.append('no failing `whoami` before recovery in the audit')
    return errors


def env_token(path):
    try:
        for line in path.read_text().splitlines():
            if line.startswith('export LLL_TOKEN='):
                return line.removeprefix('export LLL_TOKEN=').strip('\'"')
    except OSError:
        pass
    return ''


def judge_15(board, changes, after):
    seat = board.seats[0]
    name = f'bot-helper-{seat.number}'
    errors = untouched(changes, added={'members': 1})
    helper = one_added(changes, 'members')
    if helper:
        expect(errors, helper, 'helper', name=name, kind='bot', owner=seat.member_id)
    old = seat.worker / f'helper-{seat.number}.env'
    new = seat.worker / f'helper-{seat.number}-rotated.env'
    old_token, new_token = env_token(old), env_token(new)
    if not old_token or not new_token:
        errors.append(f'{old.name} and {new.name} must both hold an export LLL_TOKEN line')
    elif old_token == new_token:
        errors.append('the rotated token equals the original')
    else:
        if board.token_identity(old_token) is not None:
            errors.append('the original helper token still authenticates')
        if not helper or board.token_identity(new_token) != helper['id']:
            errors.append('the rotated helper token does not authenticate as the helper')
    calls = read_audit(board.binary, seat.worker)
    if not any(e['command'][1:2] == ['whoami'] and e['exit_code'] == 6 for e in calls):
        errors.append('no `whoami` in the audit was refused with exit 6 (the old token)')
    if not any(e['command'][1:2] == ['whoami'] and e['exit_code'] == 0 and name in e['stdout'] for e in calls):
        errors.append(f'no successful `whoami` as {name} in the audit')
    for path in (old, new):
        if path.exists():
            path.write_text(redact(path.read_text(), (old_token, new_token)))
    return errors


def pair_title(board, text):
    a, b = board.seats
    return f'{text} (workers {a.number} and {b.number})'


def seed_16(board):
    board.fixtures['issue'] = board.issue(pair_title(board, 'Migrate the upload worker'), 'Drain the queue first.', priority=2)['id']


def judge_16(board, changes, after):
    (a, b), issue = board.seats, board.fixtures['issue']
    errors = untouched(changes, added={'comments': 2, 'claims': 1}, changed={'issues': {issue: {'assignee'}}})
    expect(errors, row(after, 'issues', issue), 'issue', assignee=b.member_id)
    claims = [c for c in after['claims'] if c['issue'] == issue]
    if [c['member'] for c in claims] != [b.member_id]:
        errors.append(f'claim holder: expected only {b.name}')
    if not called(board, a, 'issue', 'claim') or not called(board, a, 'issue', 'release'):
        errors.append(f'worker {a.number}: audit lacks role A\'s claim and release')
    if any('--force' in e['command'] for e in read_audit(board.binary, b.worker)):
        errors.append(f'worker {b.number}: role B forced a command')
    comments = sorted(changes['comments']['added'], key=lambda c: c['created'])
    expected = [(a.member_id, f'fleet-16-{a.number}: handing off to {b.name}; the queue drain is next.'),
                (b.member_id, f'fleet-16-{b.number}: picked up from {a.name}.')]
    if [(c['author'], c['body'], c['issue']) for c in comments] != [(m, t, issue) for m, t in expected]:
        errors.append('comments: expected the A handoff then the B pickup, exact bodies and authors')
    return errors


def seed_17(board):
    board.fixtures['issue'] = board.issue(pair_title(board, 'Shared release notes'), 'Release notes:')['id']


def judge_17(board, changes, after):
    issue = board.fixtures['issue']
    errors = untouched(changes, changed={'issues': {issue: {'description'}}})
    lines = row(after, 'issues', issue)['description'].split('\n')
    if lines[0] != 'Release notes:':
        errors.append('the original description line was lost')
    for seat in board.seats:
        line = f'fleet-17-{seat.number}: role {seat.role} checked the upload path.'
        if lines.count(line) != 1:
            errors.append(f'worker {seat.number} line appears {lines.count(line)} times, expected once')
    if len(lines) != 3:
        errors.append(f'description has {len(lines)} lines, expected 3')
    return errors


def seed_18(board):
    board.fixtures['issue'] = board.issue(pair_title(board, 'Watch handshake'), 'Coordinate here.')['id']


def judge_18(board, changes, after):
    (a, b), handshake = board.seats, board.fixtures['issue']
    errors = untouched(changes, added={'issues': 1, 'comments': 2})
    created = one_added(changes, 'issues')
    if not created:
        return errors
    expect(errors, created, 'partner issue', title=f'fleet-18-{b.number} live event', creator=b.member_id, priority=2)
    key = board.key(created['id'], after)
    comments = sorted(changes['comments']['added'], key=lambda c: c['created'])
    expected = [(a.member_id, f'fleet-18-{a.number}: watching'), (b.member_id, f'fleet-18-{b.number}: done {key}')]
    if [(c['author'], c['body'], c['issue']) for c in comments] != [(m, t, handshake) for m, t in expected]:
        errors.append('comments: expected A "watching" then B "done KEY" on the handshake issue')
    log = a.worker / f'fleet-18-{a.number}-watch.jsonl'
    actions = set()
    try:
        for line in log.read_text().splitlines():
            if line.strip():
                event = json.loads(line)
                record = event.get('record') if isinstance(event, dict) else None
                if isinstance(record, dict) and record.get('id') == created['id']:
                    actions.add(event.get('action'))
    except (OSError, ValueError) as error:
        errors.append(f'{log.name} unreadable or not NDJSON: {error}')
    if not {'create', 'update'} <= actions:
        errors.append(f'{log.name} lacks the partner create and update events (saw {sorted(actions)})')
    keys = a.answer().get('partner_keys')
    if not isinstance(keys, list) or key not in keys:
        errors.append(f'worker {a.number}: answer partner_keys is not a list holding {key}')
    return errors


def seed_19(board):
    board.fixtures['secret'] = secret = board.create('teams', {'key': 'SECRET', 'name': 'Payroll'})['id']
    board.issue('Payroll export', 'Only payroll sees this.', team=secret)


def judge_19(board, changes, after):
    seat = board.seats[0]
    errors = untouched(changes, added={'members': 1})
    colleague = one_added(changes, 'members')
    if not colleague:
        return errors
    expect(errors, colleague, 'colleague', name=f'colleague-{seat.number}', email=f'colleague-{seat.number}@example.com',
           kind='person', scope='teams', teams=[board.team], mode='rw')
    token = board.request('/api/collections/members/impersonate/' + colleague['id'], {'duration': 60})['token']
    visible = sorted(t['key'] for t in board.records('teams', token=token))
    if visible != ['FLEET']:
        errors.append(f'the colleague sees teams {visible}, expected only FLEET')
    if not called(board, seat, 'login') or not called(board, seat, 'team', 'list'):
        errors.append('audit lacks the colleague login and team list')
    invite = seat.worker / f'invite-{seat.number}.txt'
    if invite.exists():
        invite.write_text(redact(invite.read_text()))
    return errors + answer_errors(seat, colleague_teams=['FLEET'])


def seed_20(board):
    board.fixtures['issue'] = board.issue('Upload retry flakes on slow links', 'Fixed in the last change, reportedly.', priority=2)['id']


def judge_20(board, changes, after):
    seat, issue = board.seats[0], board.fixtures['issue']
    errors = untouched(changes, added={'comments': 1}, changed={'issues': {issue: {'state'}}})
    expect(errors, row(after, 'issues', issue), 'issue', state='in-review')
    comment = one_added(changes, 'comments')
    if comment:
        expect(errors, comment, 'comment', issue=issue, author=seat.member_id)
        if not comment['body'].startswith(f'fleet-20-{seat.number}:'):
            errors.append(f'comment must start with fleet-20-{seat.number}:')
    return errors


def case(slug, seed, judge, mode='env', pair=False, person=False):
    return {'slug': slug, 'seed': seed, 'judge': judge, 'mode': mode, 'pair': pair, 'person': person}


CASES = {
    '01': case('read-and-restate', seed_none, judge_01),
    '02': case('export-subset', seed_02, judge_02),
    '03': case('finding-by-path', seed_03, judge_03),
    '04': case('orient', seed_04, judge_04),
    '05': case('browse-decisions', seed_05, judge_05),
    '06': case('create-issue', seed_none, judge_06),
    '07': case('claim-comment-close', seed_07, judge_07),
    '08': case('record-finding', seed_08, judge_08),
    '09': case('reorganize', seed_09, judge_09),
    '10': case('edit-and-reopen', seed_10, judge_10),
    '11': case('split-into-blockers', seed_11, judge_11),
    '12': case('two-teams', seed_12, judge_12, mode='noteam'),
    '13': case('script-the-loop', seed_13, judge_13),
    '14': case('recover-config', seed_14, judge_14, mode='config'),
    '15': case('bot-credentials', seed_none, judge_15, mode='override', person=True),
    '16': case('claim-handoff', seed_16, judge_16, pair=True),
    '17': case('concurrent-edit', seed_17, judge_17, pair=True),
    '18': case('watch-partner', seed_18, judge_18, pair=True),
    '19': case('scoped-invite', seed_19, judge_19, mode='override'),
    '20': case('recover-wrong-command', seed_20, judge_20),
}


def serve(args):
    os.umask(0o077)
    root = args.root.resolve()
    if root.exists():
        raise ValueError('run root must be fresh')
    private_dir(root)
    private_dir(root / 'controller')
    binary = root / 'controller' / 'lll'
    shutil.copy2(args.binary, binary)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    if digest != args.sha256:
        raise ValueError('pinned binary hash mismatch')
    harness = root / 'controller' / 'harness'
    private_dir(harness)
    for name in ('agent_dx_fleet.py', 'board_startup.py', 'real_config_guard.py'):
        shutil.copy2(Path(__file__).resolve().parent / name, harness / name)
    (root / 'fingerprint.json').write_text(json.dumps({
        'commit': args.commit, 'binary_sha256': digest,
        'harness_sha256': hashlib.sha256((harness / 'agent_dx_fleet.py').read_bytes()).hexdigest(),
        'startup_helper_sha256': hashlib.sha256((harness / 'board_startup.py').read_bytes()).hexdigest(),
    }, indent=2))
    boards = []
    live_case = None
    try:
        print(json.dumps({'ready': True, 'root': str(root), 'binary_sha256': digest}), flush=True)
        for line in sys.stdin:
            command = json.loads(line)
            action = command['action']
            if action == 'provision':
                assert not boards, 'stop previous case before provisioning'
                live_case = command['case']
                assert live_case in CASES, 'unknown case'
                pair = CASES[live_case]['pair']
                count = command.get('workers', 10)
                assert count >= 1 and (not pair or count % 2 == 0), 'pair cases need an even worker count'
                run = command.get('run', 1)
                work = root / f'case-{live_case}-run-{run}'
                controls = root / 'controller' / work.name
                assert not work.exists() and not controls.exists(), 'case/run paths must be fresh'
                private_dir(work)
                private_dir(controls)
                seats = [Seat(work / f'{n:02}', f'{n:02}', CASES[live_case]['person'])
                         for n in range(1, count + 1)]
                groups = [seats[i:i + 2] for i in range(0, count, 2)] if pair else [[s] for s in seats]
                for group in groups:
                    boards.append(Board(binary, controls, live_case, group))
                print(json.dumps({'provisioned': count, 'case': live_case, 'slug': CASES[live_case]['slug'],
                                  'rules': f'docs/agent-dx-fleet/rules/{live_case}-{CASES[live_case]["slug"]}.md',
                                  'workdir': str(work),
                                  'workers': [{'number': s.number, 'role': s.role if pair else None,
                                               'partner': next((o.number for o in g if o is not s), None),
                                               'directory': str(s.worker), 'wrapper': str(s.worker / 'lll')}
                                              for g in groups for s in g]}), flush=True)
            elif action == 'judge':
                rows = [b.judge() for b in boards]
                result = {'case': live_case, 'boards': rows, 'artifacts_passed': sum(r['pass'] for r in rows),
                          'artifacts_total': len(rows)}
                (boards[0].seats[0].worker.parent / 'ground-truth.json').write_text(json.dumps(result, indent=2))
                print(json.dumps(result), flush=True)
            elif action == 'stop':
                endpoints = [b.api for b in boards] + [b.board for b in boards]
                for b in boards:
                    b.close()
                for endpoint in endpoints:
                    url = urllib.parse.urlsplit(endpoint)
                    with socket.socket() as listener:
                        assert listener.connect_ex((url.hostname, url.port)) != 0, 'owned listener remains live'
                shutil.rmtree(root / 'controller' / boards[0].seats[0].worker.parent.name)
                boards.clear()
                print(json.dumps({'stopped': True, 'listeners_gone': len(endpoints), 'credentials_removed': True}), flush=True)
            elif action == 'exit':
                break
            else:
                raise ValueError('unknown controller action')
    finally:
        for b in boards:
            b.close()
        for path in (root / 'controller').iterdir():
            if path.is_dir():
                shutil.rmtree(path)
        print(json.dumps({'controller_exited': True}), flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'wrapper':
        wrapper_main()
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--sha256', required=True)
    serve(parser.parse_args())
