"""A password flag given '-' never echoes the secret (#340 review).

Under a terminal, `lll login --password -` read a plain line with echo on and
no prompt, so the password landed in scrollback. This drives the flags that
take '-' through a real pseudo-terminal, types a password, and asserts it is
not echoed back and a prompt was shown. Piped empty stdin is a usage error
(exit 2) naming the flag. No server is needed: the read happens before lll
talks to one, so LLL_URL points at a closed port.
"""
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time

binary = str(Path(sys.argv[1]).resolve())
SECRET = 'tty-secret-7f3a'


def run_on_tty(args, env, cwd):
    """Run lll on a pty, type SECRET once a prompt appears, return all output."""
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execve(binary, [binary, *args], env)
    out = b''
    typed = False
    deadline = time.time() + 30
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        if not typed and b'assword' in out:
            os.write(fd, (SECRET + '\n').encode())
            typed = True
    os.waitpid(pid, 0)
    return out.decode(errors='replace'), typed


def main():
    with tempfile.TemporaryDirectory(prefix='lll-password-tty-') as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_'))}
        env.update(HOME=directory, LLL_URL='http://127.0.0.1:9')
        cases = [
            # --url: a login refuses a url only LLL_URL named (LLL-688).
            ['login', '--url', 'http://127.0.0.1:9', '--email', 'a@example.com', '--password', '-'],
            ['member', 'set-password', 'alice', '--old-password', '-', '--password', 'new-password-1'],
            ['token', 'create', 'bot-x', '--admin-email', 'a@example.com', '--admin-password', '-'],
        ]
        wrong = []
        for args in cases:
            out, typed = run_on_tty(args, env, directory)
            if not typed:
                wrong.append(f"lll {' '.join(args)}: no password prompt on a terminal: {out[:200]!r}")
            elif SECRET in out:
                wrong.append(f"lll {' '.join(args)}: echoed the password: {out[:200]!r}")
        for args, flag in [(cases[0], '--password'), (cases[1], '--old-password')]:
            done = subprocess.run([binary, *args], cwd=directory, env=env, text=True,
                                  capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
            if done.returncode != 2 or f'{flag} -: stdin was empty' not in done.stderr:
                wrong.append(f"lll {' '.join(args)} </dev/null: exit {done.returncode}: {done.stderr.strip()[:200]}")
    for line in wrong:
        print(line)
    assert not wrong, f'{len(wrong)} password-stdin cases failed'
    print(f'Password stdin: {len(cases)} flags prompt without echo on a terminal; empty pipes exit 2')


main()
