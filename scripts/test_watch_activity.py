#!/usr/bin/env python3
"""Real comment/claim wake-ups, attribution, scope and measured latency."""
import http.server
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error

from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


deliveries = queue.Queue()


class Receiver(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        assert self.headers.get('X-LLL-Secret') == 'activity-test-secret'
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        payload['_receiver_path'] = self.path
        deliveries.put((time.monotonic(), payload))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


receiver = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
threading.Thread(target=receiver.serve_forever, daemon=True).start()
watchers = []
try:
    with tempfile.TemporaryDirectory(prefix='lll-watch-activity-') as directory:
        root = Path(directory)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
        env.update(HOME=str(root), USER='activity-owner', LLL_BIND='127.0.0.1', LLL_TEAM='ACT',
                   LLL_URL=f'http://127.0.0.1:{port()}', LLL_BOARD_TOKEN='activity-test-board',
                   LLL_ADMIN_EMAIL='activity@example.invalid', LLL_ADMIN_PASSWORD='activity-test-password')
        log = root / 'server.log'
        with log.open('w') as output:
            server = subprocess.Popen([binary, 'up', '--no-open', '--pb-dir', str(root / 'data'), '--port', str(port())],
                                      cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            api = wait_for_endpoints(log)['db_url']

            def request(path, body=None, token='', method=None):
                req = urllib.request.Request(api + path, method=method,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
                try:
                    response = urllib.request.urlopen(req, timeout=15)
                except urllib.error.HTTPError as error:
                    raise AssertionError((path, error.code, error.read().decode())) from error
                with response:
                    return json.load(response)

            admin = request('/api/collections/_superusers/auth-with-password',
                            {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})['token']
            owner = next(m for m in request('/api/collections/members/records', token=admin)['items'] if m['name'] == 'activity-owner')

            def impersonate(member):
                return request('/api/collections/members/impersonate/' + member['id'], {'duration': 3600}, admin)['token']

            token = impersonate(owner)
            client = {k: v for k, v in env.items() if not k.startswith('LLL_')}
            client.update(LLL_URL=api, LLL_TEAM='ACT', LLL_TOKEN=token)

            def cli(*args, who=token):
                p = subprocess.run([binary, *args], env=dict(client, LLL_TOKEN=who), cwd=root,
                                   capture_output=True, text=True, timeout=30)
                assert p.returncode == 0, (args, p.returncode, p.stdout, p.stderr)
                return p.stdout

            team = next(t for t in request('/api/collections/teams/records', token=token)['items'] if t['key'] == 'ACT')
            project = request('/api/collections/projects/records', {'team': team['id'], 'name': 'Selected', 'status': 'planned'}, token)
            other_project = request('/api/collections/projects/records', {'team': team['id'], 'name': 'Excluded', 'status': 'planned'}, token)

            def issue(title, project_id):
                return request('/api/collections/issues/records', {'team': team['id'], 'title': title,
                               'state': 'todo', 'project': project_id, 'assignee': owner['id']}, token)

            target = issue('Wake this coordinator', project['id'])
            excluded = issue('Outside project', other_project['id'])
            key = 'ACT-' + str(target['number'])
            cli('webhook', 'add', f'http://127.0.0.1:{receiver.server_port}/events', '--project', 'Selected',
                '--secret', 'activity-test-secret', '--activity')
            cli('webhook', 'add', f'http://127.0.0.1:{receiver.server_port}/legacy', '--project', 'Selected',
                '--secret', 'activity-test-secret')

            def member(name, **extra):
                return request('/api/collections/members/records', dict(name=name, email=name + '@example.invalid',
                    password='activity-member-password', passwordConfirm='activity-member-password', **extra), admin)

            guest = member('activity-guest', scope='teams', teams=[team['id']], mode='ro', kind='person')
            guest_token = impersonate(guest)
            operator = member('activity-rescuer', scope='all', mode='rw', kind='person')
            operator_token = impersonate(operator)
            bot = member('bot-hidden-activity', kind='bot', owner=owner['id'], scope='all', mode='rw')
            bot_token = impersonate(bot)

            def start_watch(name, who, ready=False, activity=True):
                out, err = root / (name + '.jsonl'), root / (name + '.stderr')
                with out.open('w') as stdout, err.open('w') as stderr:
                    p = subprocess.Popen([binary, 'watch', '--project', 'Selected', '--json', *(['--ready'] if ready else []), *(['--activity'] if activity else [])],
                        env=dict(client, LLL_TOKEN=who), cwd=root, stdout=stdout, stderr=stderr)
                watchers.append(p)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    assert p.poll() is None, err.read_text()
                    if ('watch: ready (agenda subscription accepted)' if ready else 'watch: ready (query subscription accepted)') in err.read_text():
                        return out
                    time.sleep(.02)
                raise AssertionError('watch did not accept its subscriptions')

            full_out = start_watch('full', token)
            guest_out = start_watch('guest', guest_token)
            ready_out = start_watch('ready', token, ready=True)
            default_out = start_watch('default', token, activity=False)

            def events(path):
                return [json.loads(line) for line in path.read_text().rsplit('\n', 1)[0].splitlines() if line]

            def wait_event(path, topic, action, record_id=None):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    for event in events(path):
                        if event['topic'] == topic and event['action'] == action and (record_id is None or event['record']['id'] == record_id):
                            return event
                    time.sleep(.02)
                raise AssertionError(f'missing {topic}/{action} event')

            # Excluded activity goes first; the following positive event is a delivery sentinel.
            excluded_comment = request('/api/collections/comments/records', {'issue': excluded['id'], 'body': 'excluded'}, token)
            began = time.monotonic()
            comment = json.loads(cli('issue', 'comment', key, '-b', 'wake immediately', '--agent', 'commenter', '--json'))
            event = wait_event(full_out, 'comments', 'create', comment['id'])
            watch_latency = time.monotonic() - began
            assert event['key'] == key and event['author'] == owner['id'] and event['author_kind'] == 'person', event
            assert event['author_name'] == 'activity-owner' and event['agent'] == 'commenter', event
            received = []
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                received_at, payload = deliveries.get(timeout=10)
                received.append(payload)
                if payload['topic'] == 'comments' and payload['record']['id'] == comment['id']:
                    assert payload['key'] == key and payload['author'] == owner['id'], payload
                    break
            else:
                raise AssertionError('webhook did not wake')
            webhook_latency = received_at - began
            assert watch_latency < 10 and webhook_latency < 10
            wait_event(ready_out, "comments", "create", comment["id"])

            request('/api/lll/issues/' + target['id'] + '/claim',
                    {'agent': 'worker', 'event_actor': operator['id'], 'event_source': 'system'}, token)
            acquired = wait_event(full_out, 'claims', 'create')
            claim_id = acquired['record']['id']
            assert acquired['author'] == owner['id'] and acquired['agent'] == 'worker', acquired
            cli('issue', 'claim', key, '--renew', '--agent', 'worker')
            renewed = wait_event(full_out, 'claims', 'update', claim_id)
            assert renewed['author'] == owner['id'], renewed
            cli('issue', 'release', key, '--force', '--reason', 'recovery proof', '--agent', 'rescuer', who=operator_token)
            released = wait_event(full_out, 'claims', 'delete', claim_id)
            assert released['author'] == operator['id'] and released['agent'] == 'rescuer', released
            assert released['record']['member'] == owner['id'], released

            hidden = request('/api/collections/comments/records', {'issue': target['id'], 'body': 'hidden author'}, bot_token)
            hidden_event = wait_event(guest_out, 'comments', 'create', hidden['id'])
            assert hidden_event['author_name'] == 'hidden member' and hidden_event['author_kind'] == '', hidden_event
            assert 'bot-hidden-activity' not in json.dumps(hidden_event), hidden_event
            hidden_claim = json.loads(cli('issue', 'claim', key, '--agent', 'hidden-worker', '--json', who=bot_token))['claim']['id']
            hidden_claim_event = wait_event(guest_out, 'claims', 'create', hidden_claim)
            assert hidden_claim_event['author_name'] == 'hidden member' and hidden_claim_event['author_kind'] == '', hidden_claim_event
            assert 'bot-hidden-activity' not in json.dumps(hidden_claim_event), hidden_claim_event
            cli('issue', 'release', key, '--agent', 'hidden-worker', who=bot_token)
            hidden_release = wait_event(guest_out, 'claims', 'delete', hidden_claim)
            assert hidden_release['author_name'] == 'hidden member', hidden_release
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                claims_seen = {e['action'] for e in received if e['topic'] == 'claims' and e['record']['id'] == claim_id}
                if claims_seen == {'create', 'update', 'delete'} and any(e['record']['id'] == hidden['id'] for e in received):
                    break
                _, payload = deliveries.get(timeout=10)
                received.append(payload)
            assert not any(e['record']['id'] == excluded_comment['id'] for e in events(full_out) + events(guest_out) + received)
            claim_deliveries = [e for e in received if e['topic'] == 'claims' and e['record']['id'] == claim_id]
            assert {e['action'] for e in claim_deliveries} == {'create', 'update', 'delete'}, claim_deliveries
            deleted = next(e for e in claim_deliveries if e['action'] == 'delete')
            assert deleted['author'] == operator['id'] and deleted['record']['member'] == owner['id'], deleted
            assert events(default_out) and all(e['topic'] == 'issues' for e in events(default_out)), events(default_out)
            assert all(e['topic'] == 'issues' for e in received if e['_receiver_path'] == '/legacy'), received
            hidden_webhook = next(e for e in received if e['record']['id'] == hidden['id'])
            assert hidden_webhook['author_name'] == 'hidden member' and 'bot-hidden-activity' not in json.dumps(hidden_webhook)
            print(json.dumps({'watch_seconds': round(watch_latency, 3), 'webhook_seconds': round(webhook_latency, 3),
                              'comment_and_claim_events': 'passed', 'project_scope': 'passed', 'hidden_actor': 'passed'}))
        finally:
            for watcher in watchers:
                watcher.terminate()
                watcher.wait(timeout=10)
            server.terminate()
            server.wait(timeout=15)
finally:
    receiver.shutdown()
    receiver.server_close()
