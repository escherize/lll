#!/usr/bin/env python3
"""Missing and malformed credentials use the documented auth exit, offline."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='lll-malformed-identity-') as directory:
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=directory, LLL_CONFIG_HOME=str(Path(directory) / 'config'),
               LLL_URL='http://127.0.0.1:9', LLL_AUTO_UPDATE='0')
    for token in ['not-a-lll-token', 'header.payload', 'a.b.c', '']:
        result = subprocess.run([binary, 'whoami'], env=env | {'LLL_TOKEN': token},
                                cwd=directory, capture_output=True, text=True, timeout=15)
        assert result.returncode == 6, f'local credential failure returned {result.returncode}, expected auth exit6'
        assert not result.stdout
        assert result.stderr.startswith('Error: ')
        assert not token or token not in result.stderr, 'credential value appeared in diagnostic'
    version = subprocess.run([binary, '--version'], env=env | {'LLL_TOKEN': 'not-a-lll-token'},
                             cwd=directory, capture_output=True, text=True, timeout=15)
    assert version.returncode == 0 and not version.stderr
print('Malformed identity: missing, non-JWT, truncated and corrupted credentials exit6 without credential echo; offline version still works')
