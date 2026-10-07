#!/usr/bin/env python3
"""The REAL 1791810544_invites.js migration on a board whose member names differ
only by case (LLL-544): it must still boot, warn naming the pair, and skip the
case-folded unique name index; a board without such a pair gets the index; and a
boot after the pair is resolved adds it (gopb ensureNameIndex)."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
MIGRATION = '1791810544_invites.js'
INDEX = 'idx_members_name_nocase'
# ESC, BEL, newline, DEL, the 8-bit CSI (C1) and bidi controls (RLO, LRI).
EVIL = 'evil\x1b[2K\x07\x7f\x9b2K\u202e\u2066\nlll: all good, index added'
RAW = ['\x1b', '\x07', '\x7f', '\x9b', '\u202e', '\u2066']


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def call(base, path, body=None, token='', method=None):
    hdrs = {'Content-Type': 'application/json'}
    if token:
        hdrs['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, method=method, headers=hdrs,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        resp = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        resp = e
    return resp.status, json.loads(resp.read().decode() or 'null')


with tempfile.TemporaryDirectory(prefix='lll-name-index-') as directory:
    root = Path(directory)
    home = root / 'home'
    home.mkdir()
    data = root / 'data'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(home), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA', LLL_BIND='127.0.0.1',
               USER='alice', LLL_ADMIN_EMAIL='index@example.invalid', LLL_ADMIN_PASSWORD='local-name-index-password',
               LLL_BOARD_TOKEN='local-name-index-board')

    def boot(n):
        """Boot, wait until both endpoints answer, return (process, log path, api url)."""
        log = root / f'up{n}.log'
        with log.open('w') as output:
            child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()), '--pb-dir', str(data)],
                                     cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            return child, log, wait_for_endpoints(log)['db_url']
        except BaseException:
            child.terminate()
            child.wait(timeout=10)
            raise

    def stop(child):
        child.terminate()
        child.wait(timeout=10)

    def db():
        return sqlite3.connect(data / 'data.db')

    def has_index():
        with db() as conn:
            return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?", (INDEX,)).fetchone()[0] == 1

    # 1. No case pair: the migration adds the index.
    child, log, api = boot(1)
    stop(child)
    assert has_index(), 'a board without a case pair did not get the index'

    # 2. Roll the board back to before the migration, as an upgrading board
    # would be, and give it "Alice" beside the boot member "alice" (legal under
    # the old case-sensitive idx_members_name).
    with db() as conn:
        conn.execute(f'DROP INDEX {INDEX}')
        (indexes,) = conn.execute("SELECT indexes FROM _collections WHERE name='members'").fetchone()
        kept = [i for i in json.loads(indexes) if INDEX not in i]
        conn.execute("UPDATE _collections SET indexes=? WHERE name='members'", (json.dumps(kept),))
        conn.execute("DELETE FROM _collections WHERE name='invites'")
        conn.execute('DROP TABLE invites')
        conn.execute('DELETE FROM _migrations WHERE file=?', (MIGRATION,))
        cols = [r[1] for r in conn.execute('PRAGMA table_info(members)')]
        base = dict(zip(cols, conn.execute("SELECT * FROM members WHERE name='alice'").fetchone()))
        # A second pair whose names carry an escape sequence, a bell and a
        # newline that would forge an "all good" line if printed raw.
        for rid, name in [('upperalice00001', 'Alice'), ('evillower000001', EVIL), ('evilupper000001', EVIL.upper())]:
            row = dict(base, id=rid, name=name, email=f'{rid}@example.test', tokenKey=f'{rid}-token-key-0123456789abcdef')
            conn.execute(f"INSERT INTO members ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [row[c] for c in cols])

    child, log, api = boot(2)
    try:
        output = log.read_text()
        assert '"Alice", "alice"' in output, output
        # Member names reach the operator's terminal quoted: no raw escape,
        # bell or newline, so no forged line.
        assert not any(c in output for c in RAW), repr(output)
        assert not any(line.startswith('lll: all good') for line in output.splitlines()), output
        # Both halves warn: the migration itself, and the boot-time retry.
        assert 'lll: member names differ only by case' in output, output
        assert 'warning: member names differ only by case' in output, output
        assert not has_index(), 'the index was added despite a case pair'
        _, su = call(api, '/api/collections/_superusers/auth-with-password',
                     {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})
        su = su['token']
        # The migration still ran: the invites collection exists.
        assert call(api, '/api/collections/invites/records', token=su)[0] == 200
        # Nobody was renamed.
        names = sorted(m['name'] for m in call(api, '/api/collections/members/records?perPage=200', token=su)[1]['items'])
        assert 'Alice' in names and 'alice' in names, names
        # Without the index, two members renaming themselves to a case pair
        # at the same moment must not both win (nameWrites serializes the
        # check and the save), or the pair would keep the index away forever.
        def person(name):
            body = {'name': name, 'email': f'{name}@example.test', 'password': 'pw12345678',
                    'passwordConfirm': 'pw12345678', 'kind': 'person', 'scope': 'all', 'mode': 'ro'}
            code, rec = call(api, '/api/collections/members/records', body, su)
            assert code == 200, rec
            tok = call(api, '/api/collections/members/auth-with-password',
                       {'identity': body['email'], 'password': body['password']})[1]['token']
            return rec['id'], tok
        writers = [person('racer-a'), person('racer-b')]
        for i in range(20):
            barrier, results = threading.Barrier(2), [None, None]

            def rename(w, name):
                member_id, tok = writers[w]
                barrier.wait()
                results[w] = call(api, f'/api/collections/members/records/{member_id}', {'name': name}, tok, 'PATCH')[0]
            threads = [threading.Thread(target=rename, args=(w, n)) for w, n in enumerate([f'Twin{i}', f'twin{i}'])]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            assert sorted(results) == [200, 400], (i, results)
        # 3. An administrator resolves the pairs; the next boot adds the index.
        assert call(api, '/api/collections/members/records/upperalice00001', {'name': 'alice-two'}, su, 'PATCH')[0] == 200
        assert call(api, '/api/collections/members/records/evilupper000001', {'name': 'evil-two'}, su, 'PATCH')[0] == 200
    finally:
        stop(child)
    child, log, api = boot(3)
    stop(child)
    assert 'differ only by case' not in log.read_text(), log.read_text()
    assert has_index(), 'the index did not appear after the pair was resolved'
    print('name index migration: ok')
