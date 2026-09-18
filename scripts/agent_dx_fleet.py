#!/usr/bin/env python3
"""Own isolated lll fleet instances and judge artifacts independently over REST."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from board_startup import wait_for_endpoints

COLLECTIONS = ('teams', 'members', 'labels', 'projects', 'issues', 'comments',
               'docs', 'claims', 'views', 'favorites', 'webhooks')
TARGET_TITLE = 'Retry loses the issue comment'
TARGET_BODY = 'A socket reset caused the retry to skip the comment. Preserve one comment and report the saved result.'
CREATE_BODY = 'Retry a dropped upload once and preserve the saved attachment.'


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
    return env


def redact(text, values=()):
    for value in values:
        if value:
            text = text.replace(value, '[REDACTED]')
    text = re.sub(r'[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}', '[REDACTED JWT]', text)
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


def wrapper_main():
    worker = Path(sys.argv[2]).resolve()
    binary = Path(sys.argv[3]).resolve()
    url, token, team = connection(worker / 'conn.txt')
    env = clean_env(worker / 'home')
    env.update(LLL_URL=url, LLL_TOKEN=token, LLL_TEAM=team, LLL_AGENT='codex')
    args = sys.argv[4:]
    result = subprocess.run([str(binary), *args], cwd=worker, env=env,
                            input=sys.stdin.read() if not sys.stdin.isatty() else None,
                            text=True, capture_output=True)
    stdout = redact(result.stdout, (token,))
    stderr = redact(result.stderr, (token,))
    entry = {'command': ['lll', *args], 'exit_code': result.returncode,
             'stdout': stdout, 'stderr': stderr}
    with (worker / 'calls.jsonl').open('a') as output:
        output.write(json.dumps(entry) + '\n')
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    raise SystemExit(result.returncode)


class Instance:
    def __init__(self, binary, controller, worker, number):
        self.worker, self.number = worker, number
        self.private = controller / number
        private_dir(self.private)
        private_dir(worker)
        private_dir(worker / 'home')
        self.child = None
        self.log = self.private / 'up.log'
        self.admin_token = self.bot_token = ''
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
            person = next(m for m in self.records('members') if m['name'] == 'fleet-controller')
            person_token = self.request('/api/collections/members/impersonate/' + person['id'], {'duration': 3600})['token']
            mint_env = clean_env(self.private / 'home')
            mint_env.update(LLL_URL=self.api, LLL_TOKEN=person_token, LLL_TEAM='FLEET')
            mint = subprocess.run([str(binary), 'bot', f'bot-fleet-worker-{number}', '--duration', '3600'],
                                  cwd=self.private, env=mint_env, text=True, capture_output=True, timeout=20)
            assert mint.returncode == 0, redact(mint.stderr)
            self.bot_token = next(line.removeprefix('LLL_TOKEN=') for line in mint.stdout.splitlines() if line.startswith('LLL_TOKEN='))
            bot = next(m for m in self.records('members') if m['name'] == f'bot-fleet-worker-{number}')
            assert bot['kind'] == 'bot' and bot['owner'] == person['id']
            self.bot_id = bot['id']
            refreshed = self.request('/api/collections/members/auth-refresh', {}, token=self.bot_token)
            assert refreshed['record']['id'] == bot['id'], 'bot handshake identity mismatch'
            assert self.child.poll() is None
            team = next(t for t in self.records('teams') if t['key'] == 'FLEET')
            self.team = team['id']
            self.bug = self.create('labels', {'team': self.team, 'name': 'bug'})['id']
            self.create('labels', {'team': self.team, 'name': 'docs'})
            self.project = self.create('projects', {'team': self.team, 'name': 'Fleet sandbox', 'status': 'planned'})['id']
            self.target = self.create('issues', {'team': self.team, 'title': TARGET_TITLE, 'description': TARGET_BODY,
                                               'state': 'todo', 'priority': 2, 'creator': person['id']})['id']
            for title, body in [('Add keyboard shortcuts', 'Use the palette to move between issues.'),
                                ('Import decisions', 'Preserve the decision document links.')]:
                self.create('issues', {'team': self.team, 'title': title, 'description': body,
                                       'state': 'todo', 'priority': 3, 'creator': person['id']})
            self.create('docs', {'team': self.team, 'slug': 'retry-once', 'title': 'Retry once', 'kind': 'decision',
                                 'body': 'Retry once after inspecting the saved result. Rejected: unbounded blind retries create duplicates.'})
            self.before = self.snapshot()
            private_write(worker / 'conn.txt', f'{self.api}\n{self.bot_token}\nFLEET\n')
            assert connection(worker / 'conn.txt')[0] == self.api
            script = binary.parent / 'harness' / 'agent_dx_fleet.py'
            wrapper = f'#!/usr/bin/env python3\nimport os\nos.execv({sys.executable!r}, [{sys.executable!r}, {str(script)!r}, "wrapper", {str(worker)!r}, {str(binary)!r}, *os.sys.argv[1:]])\n'
            (worker / 'lll').write_text(wrapper)
            (worker / 'lll').chmod(0o700)
            private_write(self.private / 'receipt.json', json.dumps({'bot_id': self.bot_id, 'target': self.target,
                           'team': self.team, 'bug': self.bug, 'project': self.project, 'before': self.before}, indent=2))
        except BaseException:
            stop(self.child)
            (worker / 'conn.txt').unlink(missing_ok=True)
            raise

    def request(self, path, body=None, token=None, auth=True):
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['Authorization'] = 'Bearer ' + (token or self.admin_token)
        req = urllib.request.Request(self.api + path,
                                     data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = redact(error.read().decode(), (self.admin_token, self.bot_token))
            raise RuntimeError(f'controller REST {error.code} {path}: {detail}') from None

    def records(self, collection):
        rows = []
        page = 1
        while True:
            data = self.request(f'/api/collections/{collection}/records?perPage=200&page={page}&sort=id')
            rows.extend(data['items'])
            if page >= data['totalPages']:
                return rows
            page += 1

    def create(self, collection, body):
        return self.request(f'/api/collections/{collection}/records', body)

    def snapshot(self):
        return {name: self.records(name) for name in COLLECTIONS}

    def judge(self, case):
        after = self.snapshot()
        errors = []
        changed = 'comments' if case == '01' else 'issues'
        for name in COLLECTIONS:
            if name != changed and self.before[name] != after[name]:
                errors.append('unexpected mutation in ' + name)
        before = {row['id']: row for row in self.before[changed]}
        current = {row['id']: row for row in after[changed]}
        if any(current.get(key) != row for key, row in before.items()):
            errors.append('seeded records changed or disappeared')
        new = [row for key, row in current.items() if key not in before]
        if len(new) != 1:
            errors.append(f'expected exactly one new {changed} record, got {len(new)}')
        if len(new) == 1:
            artifact = new[0]
            if case == '01':
                expected = {'issue': self.target, 'author': self.bot_id,
                            'body': f'fleet-01-{self.number}: A socket reset made the retry skip the comment; preserve one comment and report the saved result.'}
            else:
                expected = {'team': self.team, 'creator': self.bot_id, 'state': 'todo', 'priority': 2,
                            'title': f'Repair flaky upload retry (worker {self.number})', 'description': CREATE_BODY,
                            'labels': [self.bug], 'project': self.project}
            for name, value in expected.items():
                if artifact.get(name) != value:
                    errors.append('artifact mismatch: ' + name)
        result = {'worker': self.number, 'pass': not errors, 'errors': errors, 'new_records': len(new)}
        (self.worker / 'truth.json').write_text(json.dumps(result, indent=2))
        (self.worker / 'before.json').write_text(redact(json.dumps(public_snapshot(self.before), indent=2)))
        (self.worker / 'after.json').write_text(redact(json.dumps(public_snapshot(after), indent=2)))
        return result


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
    for name in ('agent_dx_fleet.py', 'board_startup.py'):
        shutil.copy2(Path(__file__).resolve().parent / name, harness / name)
    (root / 'fingerprint.json').write_text(json.dumps({
        'commit': args.commit, 'binary_sha256': digest,
        'harness_sha256': hashlib.sha256((harness / 'agent_dx_fleet.py').read_bytes()).hexdigest(),
        'startup_helper_sha256': hashlib.sha256((harness / 'board_startup.py').read_bytes()).hexdigest(),
    }, indent=2))
    instances = []
    live_case = None
    try:
        print(json.dumps({'ready': True, 'root': str(root), 'binary_sha256': digest}), flush=True)
        for line in sys.stdin:
            command = json.loads(line)
            action = command['action']
            if action == 'provision':
                assert not instances, 'stop previous case before provisioning'
                live_case = command['case']
                assert live_case in ('01', '05')
                run = command.get('run', 1)
                work = root / f'case-{live_case}-run-{run}'
                controls = root / 'controller' / work.name
                assert not work.exists() and not controls.exists(), 'case/run paths must be fresh'
                private_dir(work)
                private_dir(controls)
                for n in range(1, 11):
                    number = f'{n:02}'
                    instances.append(Instance(binary, controls, work / number, number))
                print(json.dumps({'provisioned': len(instances), 'case': live_case, 'workdir': str(work),
                                  'workers': [{'number': i.number, 'directory': str(i.worker), 'wrapper': str(i.worker / 'lll')} for i in instances]}), flush=True)
            elif action == 'judge':
                rows = [i.judge(live_case) for i in instances]
                result = {'case': live_case, 'workers': rows, 'artifacts_passed': sum(r['pass'] for r in rows)}
                (instances[0].worker.parent / 'ground-truth.json').write_text(json.dumps(result, indent=2))
                print(json.dumps(result), flush=True)
            elif action == 'stop':
                endpoints = [i.api for i in instances] + [i.board for i in instances]
                for i in instances:
                    stop(i.child)
                    (i.worker / 'conn.txt').unlink()
                for endpoint in endpoints:
                    url = urllib.parse.urlsplit(endpoint)
                    with socket.socket() as listener:
                        assert listener.connect_ex((url.hostname, url.port)) != 0, 'owned listener remains live'
                shutil.rmtree(root / 'controller' / instances[0].worker.parent.name)
                instances.clear()
                print(json.dumps({'stopped': True, 'listeners_gone': len(endpoints), 'credentials_removed': True}), flush=True)
            elif action == 'exit':
                break
            else:
                raise ValueError('unknown controller action')
    finally:
        for i in instances:
            stop(i.child)
            (i.worker / 'conn.txt').unlink(missing_ok=True)
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
