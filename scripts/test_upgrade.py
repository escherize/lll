#!/usr/bin/env python3
"""LLL-608: `lll upgrade` picks its command from where the binary lives.

Copies of the built binary stand in a fake Homebrew Cellar (reached through a
bin/ symlink, as Homebrew installs it), a checkout's target/.lisette/bin, and a
plain ~/bin. A stub `brew` on PATH records its arguments, so neither Homebrew
nor the network is touched.
"""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

binary = Path(sys.argv[1]).resolve()
# Printed before every plan (LLL-655).
NOTES = ("if this machine runs the server ('lll up'): stop it and back up its data directory first "
         "(with Homebrew, run 'lll upgrade --dry-run' until that is done); "
         "the new version migrates the database on its first start, and the backup is the way back\n"
         "upgrade the server and its clients together: a client older than its server may lack commands "
         "the server expects\n")

with tempfile.TemporaryDirectory(prefix='lll-upgrade-') as directory:
    root = Path(directory).resolve()
    record = root / 'brew-args'
    stub = root / 'stub'
    stub.mkdir()
    (stub / 'brew').write_text(f'#!/bin/sh\necho "$@" > {record}\n')
    (stub / 'brew').chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith('LLL_')}
    env.update(HOME=str(root / 'home'), PATH=f'{stub}:{env["PATH"]}', LC_ALL='C')

    def place(rel):
        path = root / rel
        path.parent.mkdir(parents=True)
        shutil.copy2(binary, path)
        return path

    def upgrade(exe, *args):
        r = subprocess.run([str(exe), 'upgrade', *args], env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        return r.stdout

    cellar = place('Cellar/lll/0.6.1/bin/lll')
    (root / 'brew-bin').mkdir()
    brew = root / 'brew-bin' / 'lll'
    brew.symlink_to(cellar)
    out = upgrade(brew, '--dry-run')
    assert out == NOTES + 'lll was installed with Homebrew; would run: brew upgrade lll\n', out
    assert not record.exists(), 'dry run ran brew'
    out = upgrade(brew)
    assert out == NOTES + 'lll was installed with Homebrew; running: brew upgrade lll\n', out
    assert record.read_text() == 'upgrade lll\n', record.read_text()
    record.unlink()

    checkout = place('repo/target/.lisette/bin/lll')
    for args in [('--dry-run',), ()]:
        out = upgrade(checkout, *args)
        assert out == NOTES + (f'lll was built from the checkout at {root}/repo; lll does not rebuild itself. Run:\n'
                       f'  cd {root}/repo && git pull && mise run build\n'), out

    release = place('home/bin/lll')
    goos = platform.system().lower()
    goarch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine(), platform.machine())
    url = f'https://github.com/escherize/lll/releases/latest/download/lll-{goos}-{goarch}'
    for args in [('--dry-run',), ()]:
        out = upgrade(release, *args)
        assert out == NOTES + ('lll was installed from a release download; lll does not replace its own binary. Run:\n'
                       f'  curl -LsSf -o {release}.new {url} && chmod +x {release}.new'
                       f' && mv {release}.new {release}\n'), out
    assert release.read_bytes() == binary.read_bytes(), 'the binary replaced itself'
    assert not record.exists(), 'a non-Homebrew install ran brew'

print('upgrade: ok')
