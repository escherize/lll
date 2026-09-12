#!/usr/bin/env python3
"""Exercise owned-child cleanup under the same Bash EXIT trap as the gates."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

LIB = Path(__file__).resolve().with_name('lib.sh')


class ReapTests(unittest.TestCase):
    def run_shell(self, script, directory):
        return subprocess.run(
            ['bash', '-c', script, 'reap-test', str(LIB), directory],
            env=dict(os.environ, LC_ALL='C', E2E_REAP_GRACE='0.15'),
            capture_output=True, text=True, timeout=10)

    def test_only_parent_runs_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_shell(r'''
set -euo pipefail
source "$1"
probe_dir=$2
cleanup() { printf '%s\n' "$BASH_SUBSHELL" >> "$probe_dir/cleanup"; rm -f "$probe_dir/live"; }
e2e_trap_cleanup cleanup
touch "$probe_dir/live"
for i in $(seq 1 20); do
  sleep 30 &
  child=$!
  e2e_reap "$child"
  if kill -0 "$child" 2>/dev/null; then echo 'child survived reap' >&2; exit 1; fi
  if [ ! -f "$probe_dir/live" ]; then echo 'watchdog ran parent cleanup' >&2; exit 1; fi
done
[ ! -e "$probe_dir/cleanup" ]
''', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            self.assertEqual(Path(directory, 'cleanup').read_text().splitlines(), ['0'])
            self.assertFalse(Path(directory, 'live').exists())

    def test_term_resistant_child_is_killed_and_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_shell(r'''
set -euo pipefail
source "$1"
probe_dir=$2
python3 -c '
import pathlib, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path(sys.argv[1]).touch()
time.sleep(30)
' "$probe_dir/ready" &
child=$!
cleanup() { kill -9 "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; }
e2e_trap_cleanup cleanup
for i in $(seq 1 100); do
  [ -f "$probe_dir/ready" ] && break
  sleep 0.01
done
[ -f "$probe_dir/ready" ]
e2e_reap "" "$child"
if kill -0 "$child" 2>/dev/null; then echo 'TERM-resistant child survived reap' >&2; exit 1; fi
e2e_reap "" "$child"
''', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')

    def test_cleanup_preserves_exit_and_signal_statuses(self):
        for ending, status, code in [('exit 23', 23, 23), ('kill -TERM $$', 143, -15),
                                     ('kill -INT $$', 130, -2), ('kill -HUP $$', 129, -1)]:
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as directory:
                result = self.run_shell(r'''
source "$1"
probe_dir=$2
cleanup() { printf '%s:%s\n' "$BASH_SUBSHELL" "$1" >> "$probe_dir/cleanup"; }
e2e_trap_cleanup cleanup
(exit 7) || true
[ ! -e "$probe_dir/cleanup" ] || exit 99
''' + ending, directory)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(Path(directory, 'cleanup').read_text().splitlines(), [f'0:{status}'])


if __name__ == '__main__':
    unittest.main()
