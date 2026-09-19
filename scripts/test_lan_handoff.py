#!/usr/bin/env python3
"""Cold local LAN/Tailscale board, ten person credentials, independent clients."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--bind', default='127.0.0.2')
parser.add_argument('--docker', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
binary = root / 'target/.lisette/bin/lll'


def free_port(host):
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def stop(child):
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


def boot(work, home, data, port, log):
    env = {k: v for k, v in os.environ.items()
           if k != 'HOME' and not k.startswith(('LLL_', 'XDG_'))}
    env['HOME'] = str(home)
    env['LLL_URL'] = 'https://hosted.example.invalid'
    env['LLL_TOKEN'] = 'fake-hosted-token'
    env['LLL_WEB_URL'] = 'https://hosted.example.invalid'
    with log.open('w') as output:
        child = subprocess.Popen(
            [str(binary), 'up', '--bind', args.bind, '--no-open',
             '--port', str(port), '--pb-dir', str(data)],
            cwd=work, env=env, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True)
    for _ in range(120):
        text = log.read_text()
        if re.search(r'^board  http://[^\s]+$', text, re.M):
            return child, env, text
        if child.poll() is not None:
            raise AssertionError('board exited before startup: ' +
                                 '\n'.join(line for line in text.splitlines()
                                           if 'token' not in line and 'password' not in line)[-1500:])
        time.sleep(.1)
    stop(child)
    raise AssertionError('board did not start in 12 seconds')


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


with tempfile.TemporaryDirectory(prefix='lll-lan-handoff-test-') as name:
    base = Path(name)
    home = base / 'home'
    home.mkdir()
    machine = home / '.config/lll'
    machine.mkdir(parents=True)
    (machine / 'lll.toml').write_text(
        'url = "https://hosted.example.invalid"\ntoken = "fake-hosted-token"\n')
    work = base / 'unrelated-work'
    work.mkdir()
    (work / '.lll.toml').write_text('team = "HACK"\n')
    data = base / 'data'
    port = free_port(args.bind)
    children = []
    try:
        child, env, text = boot(work, home, data, port, base / 'first.log')
        children.append(child)
        board = re.search(r'^board  (http://[^\s]+)$', text, re.M)[1]
        assert urllib.parse.urlsplit(board).hostname == args.bind
        assert 'hosted.example.invalid' not in text
        token_file = data / '.lll-board-token'
        admin_file = data / '.lll-admin.json'
        assert token_file.exists() and admin_file.exists()
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(admin_file.stat().st_mode) == 0o600
        local_admin = json.loads(admin_file.read_text())
        assert local_admin['password'] != 'admin-local-123', 'known loopback admin pair escaped onto LAN'

        mint = subprocess.run([str(binary), 'member', 'passes', '--count', '10', '--prefix', 'bud'],
                              cwd=work, env=env, text=True, capture_output=True, timeout=30)
        assert mint.returncode == 0, mint.stderr
        handoffs = list(machine.glob('handoffs-*.txt'))
        assert len(handoffs) == 1, 'expected one private handoff file'
        handoff = handoffs[0]
        assert stat.S_IMODE(handoff.stat().st_mode) == 0o600
        contents = handoff.read_text()
        tokens = re.findall(r'^LLL_TOKEN=(\S+)$', contents, re.M)
        names = re.findall(r'^Person \d+: (\S+)$', contents, re.M)
        assert len(tokens) == len(set(tokens)) == len(names) == len(set(names)) == 10
        assert f'API: {board}' in contents and 'Team: HACK' in contents
        link = (machine / 'board-login-url').read_text().strip()
        assert f'Board login: {link}' in contents
        assert link.startswith(board + '/?board_token=')
        assert stat.S_IMODE((machine / 'board-login-url').stat().st_mode) == 0o600
        assert stat.S_IMODE((machine / 'local-admin.json').stat().st_mode) == 0o600

        for index, (member, token) in enumerate(zip(names, tokens), 1):
            client = base / f'client-{index:02d}'
            client.mkdir()
            client_env = {k: v for k, v in env.items() if not k.startswith(('LLL_', 'XDG_'))}
            client_env.update(HOME=str(client), LLL_CONFIG_HOME=str(client / 'config'),
                              LLL_URL=board, LLL_TOKEN=token, LLL_TEAM='HACK')
            check = subprocess.run([str(binary), 'whoami'], cwd=client, env=client_env,
                                   text=True, capture_output=True, timeout=8)
            assert check.returncode == 0 and member in check.stdout, (
                f'client {index} could not authenticate: {check.stderr}')
            assert 'team    HACK' in check.stdout
        payload = json.dumps({'identity': local_admin['email'],
                              'password': local_admin['password']}).encode()
        request = urllib.request.Request(
            board + '/api/collections/_superusers/auth-with-password',
            data=payload, headers={'Content-Type': 'application/json'})
        with opener().open(request, timeout=5) as response:
            supertoken = json.load(response)['token']
        request = urllib.request.Request(
            board + '/api/collections/members/records?perPage=100',
            headers={'Authorization': 'Bearer ' + supertoken})
        with opener().open(request, timeout=5) as response:
            members = json.load(response)['items']
        found = [m for m in members if m['name'] in names]
        assert len(found) == 10 and all(m['kind'] == 'person' for m in found)

        jar = http.cookiejar.CookieJar()
        browser = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        with browser.open(link, timeout=5) as response:
            assert response.status == 200 and 'board_token' not in response.url
        assert len(jar) == 1
        if args.docker:
            env_file = base / 'docker.env'
            parsed = urllib.parse.urlsplit(link)
            board_token = urllib.parse.parse_qs(parsed.query)['board_token'][0]
            env_file.write_text('BOARD_URL=' + board + '\nBOARD_TOKEN=' + board_token + '\n')
            env_file.chmod(0o600)
            docker = subprocess.run(
                ['docker', 'run', '--rm', '--env-file', str(env_file), 'alpine:latest',
                 'sh', '-c', 'wget -qO- --header "Cookie: lll_board=$BOARD_TOKEN" "$BOARD_URL/t/HACK/" 2>/dev/null | grep -q HACK'],
                text=True, capture_output=True, timeout=30)
            assert docker.returncode == 0, 'separate network namespace could not read board'

        stop(child)
        children.remove(child)
        child2, _, text2 = boot(work, home, data, port, base / 'restart.log')
        children.append(child2)
        assert re.search(r'^board  (http://[^\s]+)$', text2, re.M)[1] == board
        assert (machine / 'board-login-url').read_text().strip() == link
        client_env = {k: v for k, v in env.items() if not k.startswith(('LLL_', 'XDG_'))}
        client_env.update(HOME=str(base / 'client-01'), LLL_CONFIG_HOME=str(base / 'client-01/config'),
                          LLL_URL=board, LLL_TOKEN=tokens[0], LLL_TEAM='HACK')
        again = subprocess.run([str(binary), 'whoami'], cwd=base / 'client-01',
                               env=client_env, text=True, capture_output=True, timeout=8)
        assert again.returncode == 0 and names[0] in again.stdout
        print(f'{args.bind}: 10 distinct person tokens, isolated clients, board login and stable reboot PASS')
    finally:
        for child in children:
            stop(child)
