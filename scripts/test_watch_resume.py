#!/usr/bin/env python3
"""LLL-816: 'lll watch' resumes from a cursor without losing an event.

Against a real board: stop a watch, write an issue's whole life while nothing
is listening, resume with --after and get every event in order; then prove
the handoff to live events, catch-up after the server restarts, refusals of
cursors this log cannot honor, filters on replay and team visibility.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


watchers = []
with tempfile.TemporaryDirectory(prefix='lll-watch-resume-') as directory:
    root = Path(directory)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root), USER='resume-owner', LLL_BIND='127.0.0.1', LLL_TEAM='RES',
               LLL_URL=f'http://127.0.0.1:{port()}', LLL_BOARD_TOKEN='resume-test-board',
               LLL_ADMIN_EMAIL='resume@example.invalid', LLL_ADMIN_PASSWORD='resume-test-password')
    up = [binary, 'up', '--no-open', '--pb-dir', str(root / 'data'), '--port', str(port())]
    log = root / 'server.log'

    def start_server():
        with log.open('w') as output:
            return subprocess.Popen(up, cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)

    server = start_server()
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
                raw = response.read()
                return json.loads(raw) if raw else None

        def superuser():
            return request('/api/collections/_superusers/auth-with-password',
                           {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})['token']

        admin = superuser()
        owner = next(m for m in request('/api/collections/members/records', token=admin)['items'] if m['name'] == 'resume-owner')

        def impersonate(member):
            return request('/api/collections/members/impersonate/' + member['id'], {'duration': 3600}, admin)['token']

        token = impersonate(owner)
        client = {k: v for k, v in env.items() if not k.startswith('LLL_')}
        client.update(LLL_URL=api, LLL_TEAM='RES', LLL_TOKEN=token)

        def run(*args, who=token, team='RES'):
            return subprocess.run([binary, *args], env=dict(client, LLL_TOKEN=who, LLL_TEAM=team), cwd=root,
                                  capture_output=True, text=True, timeout=30)

        def cli(*args, **kw):
            p = run(*args, **kw)
            assert p.returncode == 0, (args, p.returncode, p.stdout, p.stderr)
            return p.stdout

        team = next(t for t in request('/api/collections/teams/records', token=token)['items'] if t['key'] == 'RES')
        other_team = request('/api/collections/teams/records', {'key': 'OTH', 'name': 'Other'}, admin)

        count = [0]

        def start_watch(*args, who=token, team='RES'):
            count[0] += 1
            out, err = root / f'w{count[0]}.out', root / f'w{count[0]}.err'
            with out.open('w') as stdout, err.open('w') as stderr:
                p = subprocess.Popen([binary, 'watch', *args], env=dict(client, LLL_TOKEN=who, LLL_TEAM=team),
                                     cwd=root, stdout=stdout, stderr=stderr)
            watchers.append(p)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                assert p.poll() is None, err.read_text()
                lines = err.read_text().splitlines()
                cursors = [l for l in lines if l.startswith('watch: cursor ')]
                if cursors:
                    assert 'watch: ready (query subscription accepted)' in lines, lines
                    return p, out, err, cursors[0].split()[-1]
                time.sleep(.02)
            raise AssertionError('watch never printed its cursor')

        def stop(p):
            p.terminate()
            p.wait(timeout=10)

        def events(path):
            return [json.loads(line) for line in path.read_text().rsplit('\n', 1)[0].splitlines() if line]

        def wait_events(path, done, timeout=10):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                seen = events(path)
                if done(seen):
                    return seen
                time.sleep(.02)
            raise AssertionError(('watch never printed the expected events', events(path)))

        def shape(seen):
            return [(e['topic'], e['action']) for e in seen]

        # --- A live watch: every event carries a cursor, in seq order.
        live, live_out, _, start_cursor = start_watch('--activity', '--json')
        assert start_cursor.startswith('v1.') and start_cursor.count('.') == 2, start_cursor
        first = json.loads(cli('issue', 'create', '-t', 'Seen live', '--json'))
        cli('issue', 'comment', first['key'], '-b', 'live comment', '--agent', 'writer')
        seen = wait_events(live_out, lambda s: len(s) >= 2)
        assert shape(seen) == [('issues', 'create'), ('comments', 'create')], seen
        created, commented = seen
        assert created['key'] == first['key'] and created['record']['id'] == first['id'], created
        assert created['changes']['title'] == {'from': None, 'to': 'Seen live'}, created
        assert created['author'] == owner['id'] and created['author_name'] == 'resume-owner' and created['author_kind'] == 'person', created
        assert commented['agent'] == 'writer' and commented['record']['body'] == 'live comment', commented
        assert commented['cursor'] == f"{start_cursor.rsplit('.', 1)[0]}.{commented['seq']}", commented
        assert created['seq'] < commented['seq'], seen
        assert created['created'].endswith('Z') and 'T' in created['created'], created
        stop(live)
        last = commented['cursor']

        # --- Nothing is listening: one issue's whole life.
        gone = json.loads(cli('issue', 'create', '-t', 'Lives and dies', '--json'))
        cli('issue', 'comment', gone['key'], '-b', 'while you were out')
        cli('issue', 'claim', gone['key'], '--agent', 'worker')
        cli('issue', 'release', gone['key'], '--agent', 'worker')
        cli('issue', 'update', gone['key'], '--state', 'in-progress')
        cli('issue', 'delete', gone['key'], '--yes')
        lifetime = [('issues', 'create'), ('comments', 'create'), ('claims', 'create'), ('issues', 'update'),
                    ('claims', 'delete'), ('issues', 'update'), ('issues', 'update'), ('issues', 'delete')]

        resumed, resumed_out, _, resumed_cursor = start_watch('--activity', '--json', '--after', last)
        assert resumed_cursor == last, (resumed_cursor, last)
        seen = wait_events(resumed_out, lambda s: len(s) >= len(lifetime))
        mine = [e for e in seen if e['key'] == gone['key']]
        assert shape(mine)[:len(lifetime)] == lifetime, shape(seen)
        seqs = [e['seq'] for e in seen]
        assert seqs == sorted(set(seqs)) and seqs[0] > commented['seq'], seqs
        state_change = mine[6]
        assert state_change['changes']['state'] == {'from': 'todo', 'to': 'in-progress'}, state_change
        deleted = mine[7]
        # The issue is gone: the record is what the delete removed.
        assert deleted['record']['id'] == gone['id'] and deleted['record']['title'] == 'Lives and dies', deleted
        assert mine[4]['record']['member'] == owner['id'], mine[4]

        # --- The same stream goes on to live events, once each.
        cli('issue', 'comment', first['key'], '-b', 'after the handoff')
        seen = wait_events(resumed_out, lambda s: any(e['record'].get('body') == 'after the handoff' for e in s))
        assert sum(e['record'].get('body') == 'after the handoff' for e in seen) == 1, seen

        # --- A dropped connection: the server restarts, a write lands before
        # the watch is back, and the watch catches up from its own cursor.
        server.terminate()
        server.wait(timeout=15)
        server = start_server()
        wait_for_endpoints(log)
        admin = superuser()  # a restart retires the earlier superuser token
        cli('issue', 'comment', first['key'], '-b', 'written while reconnecting')
        seen = wait_events(resumed_out, lambda s: any(e['record'].get('body') == 'written while reconnecting' for e in s), timeout=30)
        assert sum(e['record'].get('body') == 'written while reconnecting' for e in seen) == 1, seen
        seqs = [e['seq'] for e in seen]
        assert seqs == sorted(set(seqs)), seqs
        stop(resumed)

        # --- Reprocessing: resuming from an older cursor repeats, never skips.
        again, again_out, _, _ = start_watch('--activity', '--json', '--after', last)
        replay = wait_events(again_out, lambda s: len(s) >= len(seen))
        assert [e['seq'] for e in replay[:len(seen)]] == seqs, (replay, seqs)
        stop(again)

        # --- Without --activity the same log yields issue events only.
        plain, plain_out, _, _ = start_watch('--json', '--after', last)
        only = wait_events(plain_out, lambda s: len(s) >= 5)
        assert {e['topic'] for e in only} == {'issues'}, only
        stop(plain)

        # --- Filters judge the issue as it is now; a deleted issue's events
        # survive only a filter its row can answer.
        cli('issue', 'update', first['key'], '--state', 'done')
        done, done_out, _, _ = start_watch('--json', '--after', start_cursor, '--state', 'done')
        matched = wait_events(done_out, lambda s: any(e['changes'].get('state', {}).get('to') == 'done' for e in s))
        assert {e['key'] for e in matched} == {first['key']}, matched
        stop(done)

        # --- Text mode narrates from the log: no first-sight 'changed'.
        text, text_out, _, _ = start_watch('--after', start_cursor, '--activity')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and f"{first['key']} update state: todo -> done" not in text_out.read_text():
            time.sleep(.05)
        printed = [line.split(' ', 1)[1] for line in text_out.read_text().splitlines()]
        for line in [f"{first['key']} created: Seen live", f"{first['key']} comment create by resume-owner (agent writer)",
                     f"{gone['key']} claim acquired by resume-owner (agent worker)",
                     f"{gone['key']} update assignee: none -> resume-owner",
                     f"{gone['key']} update state: todo -> in-progress", f"{gone['key']} deleted",
                     f"{first['key']} update state: todo -> done"]:
            assert line in printed, (line, printed)
        stop(text)

        # --- Cursors this log cannot honor are refused, never read as now.
        log_id = last.split('.')[1]
        for cursor, code, words in [
                ('yesterday', 2, "--after takes a cursor that 'lll watch' printed"),
                ('v1..7', 2, "--after takes a cursor"),
                ('v2.' + log_id + '.1', 2, "--after takes a cursor"),
                ('v1.000000000000.1', 1, "belongs to another board's activity log"),
                (f'v1.{log_id}.999999', 1, "is ahead of this board's activity log")]:
            refused = run('watch', '--json', '--after', cursor)
            assert refused.returncode == code and words in refused.stderr and refused.stdout == '', (cursor, refused)
        refused = run('watch', '--ready', '--after', last)
        assert refused.returncode == 2 and '--ready cannot resume from --after' in refused.stderr, refused

        # Retention: a superuser deletes the oldest rows; a cursor from before
        # them has expired, and one at the edge still resumes.
        rows = request('/api/collections/audit_events/records?sort=seq&perPage=3', token=admin)['items']
        for row in rows[:2]:
            request('/api/collections/audit_events/records/' + row['id'], token=admin, method='DELETE')
        expired = run('watch', '--json', '--after', f'v1.{log_id}.0')
        assert expired.returncode == 1 and 'has expired' in expired.stderr and f'keeps is {rows[2]["seq"]}' in expired.stderr, expired
        edge, _, _, _ = start_watch('--json', '--after', f'v1.{log_id}.{rows[1]["seq"]}')
        stop(edge)

        # --- Visibility: a read-only member of this team reads the replay; a
        # member of another team reads none of it.
        def member(name, **extra):
            return request('/api/collections/members/records', dict(name=name, email=name + '@example.invalid',
                password='resume-member-password', passwordConfirm='resume-member-password', **extra), admin)

        guest = impersonate(member('resume-guest', scope='teams', teams=[team['id']], mode='ro', kind='person'))
        outsider = impersonate(member('resume-outsider', scope='teams', teams=[other_team['id']], mode='rw', kind='person'))
        guest_watch, guest_out, _, _ = start_watch('--activity', '--json', '--after', last, who=guest)
        guest_seen = wait_events(guest_out, lambda s: any(e['action'] == 'delete' and e['topic'] == 'issues' for e in s))
        assert [e['seq'] for e in guest_seen if e['key'] == gone['key']] == [e['seq'] for e in mine], guest_seen
        stop(guest_watch)
        outside, outside_out, _, _ = start_watch('--activity', '--json', '--after', last, who=outsider, team='OTH')
        sentinel = json.loads(cli('issue', 'create', '-t', 'Other team sentinel', '--json', who=outsider, team='OTH'))
        outside_seen = wait_events(outside_out, lambda s: any(e['key'] == sentinel['key'] for e in s))
        assert {e['key'] for e in outside_seen} == {sentinel['key']}, outside_seen
        stop(outside)

        print(json.dumps({'replayed_in_order': len(lifetime), 'handoff': 'passed', 'reconnect_catch_up': 'passed',
                          'refusals': 'passed', 'filters': 'passed', 'visibility': 'passed'}))
    finally:
        for watcher in watchers:
            if watcher.poll() is None:
                watcher.terminate()
                watcher.wait(timeout=10)
        server.terminate()
        server.wait(timeout=15)
