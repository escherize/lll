#!/usr/bin/env python3
"""Owned shared-board restart, retained identity/data and attachment guard."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.parse

binary = str(Path(sys.argv[1]).resolve())
def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]
def stop(p):
    if p.poll() is None:
        p.terminate()
        try: p.wait(timeout=15)
        except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=5)
with tempfile.TemporaryDirectory(prefix='lll-shared-reopen-') as temporary:
    root = Path(temporary)
    home, work = root/'home', root/'work'
    home.mkdir(); work.mkdir()
    env = {k:v for k,v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(home), USER='reopen-owner', LLL_AUTO_UPDATE='0')
    config = home/'.config/lll/lll.toml'
    config.parent.mkdir(parents=True)
    original_home = 'url = "https://unrelated.invalid"\nteam = "KEEP"\ntoken = "keep-private-login"\n'
    config.write_text(original_home); config.chmod(0o600)
    args = [binary, 'new', 'Shared reopen proof', '--key', 'REOPEN', '--share', '--no-open']
    def cli(*argv):
        p = subprocess.run([binary, *argv], cwd=work, env=env, capture_output=True, text=True, timeout=40)
        assert p.returncode == 0, f'{argv[:2]} exited {p.returncode}'
        return json.loads(p.stdout)
    def boot(name, argv=args, cwd=work, current_env=env):
        log = root/(name+'.log')
        with log.open('w') as out:
            p = subprocess.Popen([*argv, '--port', str(port())], cwd=cwd, env=current_env, stdout=out, stderr=subprocess.STDOUT)
        deadline = time.monotonic()+45
        while time.monotonic()<deadline:
            if p.poll() is not None: raise AssertionError(f'{name}: owned boot exited {p.returncode}')
            if 'board  login ' in log.read_text(): return p
            time.sleep(.1)
        stop(p); raise AssertionError(name+': owned boot did not become ready')
    p = boot('first')
    try:
        first = tomllib.loads((work/'.lll.toml').read_text())
        assert urllib.parse.urlsplit(first['url']).hostname not in ('127.0.0.1','localhost','::1')
        member = cli('whoami','--json')['id']
        issue = cli('issue','create','-t','Retain this issue','--json')
    finally: stop(p)
    # The second boot changes ports, but keeps the exact cached database/identity.
    p = boot('second')
    try:
        assert cli('whoami','--json')['id'] == member
        assert cli('issue','view',issue['key'],'--json')['id'] == issue['id']
    finally: stop(p)
    attached = work/'.lll.toml'
    own = attached.read_bytes()
    login_path = home/'.config/lll/logins.toml'
    logins = login_path.read_bytes()
    def refused(name):
        before = attached.read_bytes()
        result = subprocess.run([*args,'--port',str(port())], cwd=work, env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == 4 and 'attaches this directory' in result.stderr, name
        assert attached.read_bytes() == before and config.read_text() == original_home, name+' wrote configuration'
    attached.write_text('team = "OTHER"\nurl = "https://foreign.invalid"\n'); refused('wrong team')
    attached.write_text('team = "REOPEN"\nurl = "https://foreign.invalid"\n'); refused('foreign URL')
    # A valid token from a different database must not turn a reused URL into ownership.
    other_home, other_work = root/'other-home', root/'other-work'
    other_home.mkdir(); other_work.mkdir()
    other_env = dict(env, HOME=str(other_home))
    p = boot('foreign', [binary,'new','Foreign proof','--key','FOREIGN','--no-open'], other_work, other_env)
    try:
        foreign = next(iter(tomllib.loads((other_home/'.config/lll/logins.toml').read_text()).values()))
    finally: stop(p)
    attached.write_bytes(own)
    own_url = tomllib.loads(own.decode())['url']
    login_path.write_text(json.dumps(own_url)+' = '+json.dumps(foreign)+'\n')
    refused('reused URL with foreign credential')
    # A stale private cache must not mask a valid, endpoint-bound home login.
    own_token = tomllib.loads(logins.decode())[own_url.rstrip('/')]
    bound_home = 'url = '+json.dumps(own_url)+'\nteam = "REOPEN"\ntoken = '+json.dumps(own_token)+'\n'
    config.write_text(bound_home)
    p = boot('home-proof')
    try:
        assert cli('whoami','--json')['id'] == member
        assert cli('issue','view',issue['key'],'--json')['id'] == issue['id']
    finally: stop(p)
    assert config.read_text() == bound_home
    config.write_text(original_home)
    own = attached.read_bytes()
    logins = login_path.read_bytes()
    # Missing legacy credentials fail closed; the existing explicit recovery still works.
    login_path.write_text(''); refused('legacy without proof')
    login_path.write_bytes(logins)
    attached.write_text('team = "REOPEN"\n')
    p = boot('recovery', [binary,'new','Shared reopen proof','--key','REOPEN','--no-open'])
    try:
        assert cli('whoami','--json')['id'] == member
        assert cli('issue','view',issue['key'],'--json')['id'] == issue['id']
    finally: stop(p)
    assert config.read_text() == original_home
    print('Shared named board: restart/changed ports retain issue and identity; foreign/reused/wrong-team/missing-proof refusals preserve config; explicit legacy recovery passed')
