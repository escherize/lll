#!/usr/bin/env python3
"""A healthy neighboring board must not receive the startup fixture's writes."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.request

from board_startup import wait_for_endpoints


def reserve_run(low, high, count):
    for port in range(low, high - count):
        listeners = []
        try:
            for offset in range(count):
                listener = socket.socket()
                listeners.append(listener)
                listener.bind(('127.0.0.1', port + offset))
                listener.listen(4)
            return port, listeners
        except OSError:
            for listener in listeners:
                listener.close()
    raise AssertionError('no free consecutive fixture ports')


def refuse(listener):
    while True:
        try:
            connection, _ = listener.accept()
            connection.close()
        except OSError:
            return


def api(url, path, payload=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(url + path,
        data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


binary = str(Path(sys.argv[1]).resolve())
neighbor_race = '--neighbor-board-race' in sys.argv[2:]
with tempfile.TemporaryDirectory(prefix='lll-up-owned-') as directory:
    base = Path(directory)
    db, db_reservations = reserve_run(22000, 35000, 3)
    web, web_reservations = reserve_run(42000, 55000, 3)
    listeners = db_reservations + web_reservations
    processes = []
    handles = []

    def boot(name, db_port, web_port, team):
        home = base / name
        home.mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
        env.update(HOME=str(home), USER='e2euser', LLL_TEAM=team,
                   LLL_URL=f'http://127.0.0.1:{db_port}', LLL_BIND='127.0.0.1')
        log_path = home / 'up.log'
        log = log_path.open('w')
        handles.append(log)
        process = subprocess.Popen([binary, 'up', '--no-open', '--port', str(web_port),
            '--pb-dir', str(home / 'data')], cwd=home, env=env, stdout=log, stderr=log,
            start_new_session=True)
        processes.append(process)
        return wait_for_endpoints(log_path), env, home

    try:
        # Keep the requested port occupied. The neighboring board owns +1,
        # which the old harness would accept merely because health returns 200.
        db_reservations[1].close()
        web_reservations[2].close()
        competitor = None
        if neighbor_race:
            # Model a parallel bind probe while the neighbor chooses its port.
            # Its announced endpoint is authoritative even when it increments.
            competitor = socket.socket()
            listeners.append(competitor)
            competitor.bind(('127.0.0.1', web + 2))
            competitor.listen(4)
        neighbor, _, _ = boot('neighbor', db + 1, web + 2, 'OTHER')
        assert neighbor['db_url'] == f'http://127.0.0.1:{db + 1}'
        if competitor:
            assert int(neighbor['board_url'].rsplit(':', 1)[1]) >= web + 3
            competitor.close()
        db_reservations[2].close()
        for listener in (db_reservations[0], web_reservations[0], web_reservations[1]):
            threading.Thread(target=refuse, args=(listener,), daemon=True).start()
        owned, env, home = boot('owned', db, web, 'E2E')
        assert owned['db_url'] != neighbor['db_url']
        assert int(owned['db_url'].rsplit(':', 1)[1]) >= db + 2
        # Only the first two board ports remain reserved. The neighbor may
        # have moved above +2; the owned boot can legitimately reuse that hole.
        assert int(owned['board_url'].rsplit(':', 1)[1]) >= web + 2
        assert owned['board_url'] != neighbor['board_url']

        def token(url):
            return api(url, '/api/collections/_superusers/auth-with-password',
                {'identity': 'admin@local.dev', 'password': 'admin-local-123'})['token']

        neighbor_token = token(neighbor['db_url'])
        env.update(LLL_URL=neighbor['db_url'], LLL_TOKEN=neighbor_token)
        wrong = subprocess.run([binary, 'issue', 'create', '-t', 'port ownership'],
            cwd=home, env=env, capture_output=True, text=True, timeout=15)
        assert wrong.returncode != 0 and "no team with key 'E2E'" in wrong.stderr, wrong.stderr

        env.update(LLL_URL=owned['db_url'], LLL_TOKEN=token(owned['db_url']))
        correct = subprocess.run([binary, 'issue', 'create', '-t', 'port ownership'],
            cwd=home, env=env, capture_output=True, text=True, timeout=15)
        assert correct.returncode == 0 and 'Created E2E-1' in correct.stdout, correct.stderr
        rows = api(neighbor['db_url'], '/api/collections/issues/records', token=neighbor_token)
        assert rows['totalItems'] == 0, 'fixture wrote to the neighboring database'
        print('Startup port ownership: healthy neighbor, occupied ports and correct database passed; transient neighbor collision=' + str(neighbor_race))
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for handle in handles:
            handle.close()
        for listener in listeners:
            listener.close()
