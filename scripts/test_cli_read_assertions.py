#!/usr/bin/env python3
"""Read assertions diagnose failures under the suites' strict Bash settings."""
import os
from pathlib import Path
import subprocess
import tempfile

lib = Path(__file__).resolve().parent / 'lib.sh'
with tempfile.TemporaryDirectory(prefix='lll-read-assertions-') as directory:
    env = {**os.environ, 'DATA_DIR': directory, 'LC_ALL': 'C'}
    def run(helper, read):
        return subprocess.run(['bash', '-c',
            'set -euo pipefail; source "$1"; "$2" "fixture assertion" needle bash -c "$3"',
            'probe', str(lib), helper, read], env=env, text=True,
            capture_output=True, timeout=10)

    for helper in ('assert_cli_contains', 'assert_cli_lacks'):
        failed = run(helper, 'echo fixture-connection-refused >&2; exit 7')
        assert failed.returncode == 1, failed
        assert 'the read itself failed (exit 7)' in failed.stderr, failed.stderr
        assert 'fixture-connection-refused' in failed.stderr, failed.stderr
        assert 'expected' not in failed.stderr and 'did not expect' not in failed.stderr, failed.stderr
    absent = run('assert_cli_contains', 'echo other-record')
    assert absent.returncode == 1 and "expected 'needle'" in absent.stderr, absent
    present = run('assert_cli_lacks', 'echo needle')
    assert present.returncode == 1 and "did not expect 'needle'" in present.stderr, present
    assert run('assert_cli_lacks', 'echo other-record').returncode == 0
    # Early matches must still drain a large output under pipefail, without EPIPE.
    large = run('assert_cli_contains', 'echo needle; printf "%100000s" tail')
    assert large.returncode == 0, large
print('CLI read assertions: strict-shell positive/negative failures name exit/error; genuine presence/absence and large matching output preserved')
