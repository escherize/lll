#!/usr/bin/env python3
"""Exercise an installed Flatpak on a disposable Linux test account."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from board_startup import wait_for_endpoints

APP = 'io.github.escherize.lll'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    env = {key: value for key, value in os.environ.items() if not key.startswith('LLL_')}
    command = ['flatpak', 'run', APP]
    version = subprocess.check_output(command + ['--version'], text=True, env=env).strip()
    assert version == 'lll ' + args.version, version
    skill = subprocess.check_output(command + ['skill', 'get', 'software-factory'], text=True, env=env)
    assert '# How work moves through a repo tracked on lll' in skill
    with tempfile.TemporaryDirectory(prefix='lll-flatpak-smoke-') as directory:
        log = Path(directory) / 'board.log'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        # This fixture account must be disposable: the named board persists
        # inside the installed app's own private data/config directories.
        for boot in range(2):
            endpoints = None
            with log.open('w') as output:
                child = subprocess.Popen(command + ['new', 'Flatpak package smoke', '--key', 'FLAT',
                                         '--no-open', '--port', str(port)], env=env, cwd=directory,
                                         stdout=output, stderr=subprocess.STDOUT)
            try:
                endpoints = wait_for_endpoints(log, timeout=60)
                req = urllib.request.Request(endpoints['board_url'] + '/',
                        headers={'Cookie': 'lll_board=' + endpoints['board_token']})
                with urllib.request.urlopen(req, timeout=15) as response:
                    body = response.read().decode()
                    assert response.status == 200 and 'FLAT' in body
                print(f'PASS: installed Flatpak board boot {boot + 1} opens in browser')
            finally:
                # The flatpak client may exit while its sandbox stays alive.
                # Kill the owned app instance, not just the launcher process.
                subprocess.run(['flatpak', 'kill', APP], env=env, check=True)
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                if endpoints:
                    deadline = time.monotonic() + 10
                    while True:
                        try:
                            urllib.request.urlopen(endpoints['db_url'] + '/api/health', timeout=1).close()
                        except urllib.error.URLError:
                            break
                        assert time.monotonic() < deadline, 'sandbox server survived cleanup'
                        time.sleep(.1)
    print('PASS: installed version, embedded skill, local board and saved-board reopen')


if __name__ == '__main__':
    main()
