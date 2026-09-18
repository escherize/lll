"""Archive preparation tolerates late tar padding and preserves stage errors."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

SCRIPT = Path(__file__).with_name('prepare-deploy-context.sh')


class ContextPreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lll-context-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        (self.repo / 'scripts').mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.repo / 'scripts/prepare-deploy-context.sh')
        (self.repo / 'README').write_text('committed\n')
        (self.repo / '.dockerignore').write_text('target/\nnode_modules/\n')
        (self.repo / 'scripts/emit-relative.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
printf emitted > "$EMIT_MARKER"
[ "${EMIT_FAIL:-0}" = 0 ] || exit "$EMIT_FAIL"
mkdir -p target
printf generated > target/generated.go
''')
        self.git = shutil.which('git')
        self.tar = shutil.which('tar')
        for args in [('init', '-q'), ('add', '.'), ('-c', 'user.name=fixture', '-c',
            'user.email=fixture@lll.test', '-c', 'commit.gpgsign=false', '-c',
            'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture')]:
            subprocess.run([self.git, '-C', str(self.repo), *args], check=True, capture_output=True)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.write_program('lis', 'raise SystemExit(0)')
        self.write_program('git', '''
import os, signal, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
if args and args[0] == 'archive':
    failure = int(os.environ.get('ARCHIVE_FAIL', '0'))
    if failure:
        print('fixture archive failure', file=sys.stderr)
        raise SystemExit(failure)
    if os.environ.get('LATE_PADDING') == '1':
        output = next((arg.split('=', 1)[1] for arg in args if arg.startswith('--output=')), None)
        if output:
            subprocess.run([os.environ['REAL_GIT'], *args], check=True)
            with open(output, 'ab') as archive:
                archive.write(bytes(10240))
        else:
            # Padding after a complete tar archive is valid. A consumer may
            # finish at the end marker instead of waiting for a producer's
            # later writes. Make that scheduling reproducible.
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)
            archive = subprocess.check_output([os.environ['REAL_GIT'], *args])
            sys.stdout.buffer.write(archive)
            sys.stdout.buffer.flush()
            deadline = time.monotonic() + 5
            marker = Path(os.environ['TAR_MARKER'])
            while not (marker.exists() and marker.read_text() == 'finished'):
                if time.monotonic() > deadline:
                    raise SystemExit('consumer did not finish')
                time.sleep(.01)
            time.sleep(.1)
            os.write(sys.stdout.fileno(), bytes(10240))
        raise SystemExit(0)
raise SystemExit(subprocess.call([os.environ['REAL_GIT'], *args]))
''')
        self.write_program('tar', '''
import os, subprocess, sys, tarfile
with open(os.environ['TAR_MARKER'], 'w') as marker:
    marker.write('started')
failure = int(os.environ.get('EXTRACT_FAIL', '0'))
if failure:
    print('fixture extraction failure', file=sys.stderr)
    raise SystemExit(failure)
if os.environ.get('LATE_PADDING') == '1' and '-f' not in sys.argv:
    # This valid streaming consumer finishes at the tar end marker; it is
    # allowed to close without draining later padding from the producer.
    destination = sys.argv[sys.argv.index('-C') + 1]
    with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as archive:
        archive.extractall(destination, filter='data')
    os.close(sys.stdin.fileno())
    status = 0
else:
    status = subprocess.call([os.environ['REAL_TAR'], *sys.argv[1:]])
with open(os.environ['TAR_MARKER'], 'w') as marker:
    marker.write('finished')
raise SystemExit(status)
''')
        self.context = self.base / 'context'
        self.context.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        REAL_GIT=self.git, REAL_TAR=self.tar,
                        TAR_MARKER=str(self.base / 'tar-marker'), EMIT_MARKER=str(self.base / 'emit-marker'),
                        TMPDIR=str(self.base), LC_ALL='C', PYTHONUTF8='1')

    def write_program(self, name, body):
        path = self.bin / name
        path.write_text('#!' + sys.executable + '\n' + textwrap.dedent(body))
        path.chmod(0o755)

    def run_prepare(self, **settings):
        return subprocess.run([os.environ.get('CONTEXT_TEST_BASH', 'bash'), str(self.repo / 'scripts/prepare-deploy-context.sh'), str(self.context)],
                              env=dict(self.env, **settings), capture_output=True, text=True, timeout=15)

    def test_complete_archive_accepts_late_padding(self):
        result = self.run_prepare(LATE_PADDING='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.context / 'README').read_text(), 'committed\n')
        self.assertTrue((self.context / 'target/generated.go').exists())

    def test_archive_failure_keeps_its_status_and_does_not_extract(self):
        result = self.run_prepare(ARCHIVE_FAIL='42')
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertIn('archive failed (exit 42)', result.stderr)
        self.assertFalse((self.base / 'tar-marker').exists())
        self.assertFalse((self.base / 'emit-marker').exists())

    def test_extraction_failure_keeps_its_status_and_does_not_emit(self):
        result = self.run_prepare(EXTRACT_FAIL='43')
        self.assertEqual(result.returncode, 43, result.stderr)
        self.assertIn('extract failed (exit 43)', result.stderr)
        self.assertFalse((self.base / 'emit-marker').exists())

    def test_emit_failure_names_its_stage(self):
        result = self.run_prepare(EMIT_FAIL='44')
        self.assertEqual(result.returncode, 44, result.stderr)
        self.assertIn('emit failed (exit 44)', result.stderr)

    def test_context_uses_head_and_only_newly_emitted_target(self):
        (self.repo / 'README').write_text('dirty\n')
        (self.repo / 'untracked').write_text('must not ship\n')
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.context / 'README').read_text(), 'committed\n')
        self.assertFalse((self.context / 'untracked').exists())
        self.assertEqual((self.context / '.dockerignore').read_text(), 'node_modules/\n')
        self.assertTrue((self.context / 'target/generated.go').exists())


if __name__ == '__main__':
    unittest.main()
