"""Reproduce the old cwd mistakes in a disposable nested Git archive."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

from protect_archive import ArchiveError, protect


@unittest.skipIf(os.geteuid() == 0, 'root bypasses the filesystem permission mechanism')
class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base/'.private'
        self.root.mkdir()
        self.run_git('init', '-q')
        (self.root/'mise.toml').write_text('[tools]\n')
        (self.root/'read-history').write_text('#!/bin/sh\necho history\n')
        (self.root/'read-history').chmod(0o755)
        self.run_git('add', '.')
        self.run_git('-c', 'user.name=Archive Test', '-c', 'user.email=archive@example.invalid', 'commit', '-qm', 'archive fixture')
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for path in [self.root, *self.root.rglob('*')]:
            if not path.is_symlink():
                path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
        self.temp.cleanup()

    def run_git(self, *args, success=True):
        p = subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True,
                           env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
        self.assertEqual(p.returncode == 0, success, p.stderr)
        return p.stdout

    def contents(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_real_writes_fail_and_history_remains_readable(self):
        before = self.contents()
        with self.assertRaises(ArchiveError):
            protect(self.root, check=True)
        protect(self.root)
        protect(self.root, check=True)
        with self.assertRaises(PermissionError):
            with (self.root/'mise.toml').open('a') as output:
                output.write('[tasks]\n')
        # These are the original command shapes, executed with cwd in .private.
        p = subprocess.run(['bash', '-c', 'git checkout -b accidental'], cwd=self.root, capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        self.run_git('worktree', 'add', '-b', 'accidental-worktree', str(self.base/'wrong-worktree'), success=False)
        self.assertNotIn('accidental', self.run_git('branch', '--list'))
        self.assertEqual(self.run_git('status', '--porcelain'), '')
        self.assertIn('archive fixture', self.run_git('log', '-1', '--oneline'))
        self.assertEqual(subprocess.check_output([str(self.root/'read-history')], text=True).strip(), 'history')
        self.assertEqual(self.contents(), before)
        self.assertIn('0 entries', protect(self.root))

    def test_dirty_archive_is_not_changed(self):
        (self.root/'mise.toml').write_text('uncommitted work')
        mode = self.root.stat().st_mode
        with self.assertRaises(ArchiveError):
            protect(self.root)
        self.assertEqual(self.root.stat().st_mode, mode)
        self.assertTrue(os.access(self.root/'mise.toml', os.W_OK))

    def test_symlinks_are_not_followed(self):
        external = self.base/'external'
        external.write_text('keep writable')
        (self.root/'link').symlink_to(external)
        with self.assertRaises(ArchiveError):
            protect(self.root)
        self.assertTrue(os.access(external, os.W_OK))
        self.assertTrue(os.access(self.root, os.W_OK))


if __name__ == '__main__':
    unittest.main()
