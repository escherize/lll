#!/usr/bin/env python3
"""Protect the retired sidecar without changing its contents or Git history."""
import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys


class ArchiveError(Exception):
    pass


def archive_entries(root):
    if root.is_symlink() or not root.is_dir() or (root/'.git').is_symlink() or not (root/'.git').is_dir():
        raise ArchiveError('archive must be a standalone directory with its own .git directory')
    entries = [root, *root.rglob('*')]
    for path in entries:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ArchiveError(f'refusing a symlink or special file: {path}')
        if info.st_uid != os.getuid():
            raise ArchiveError(f'archive entry is owned by another user: {path}')
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1 and info.st_mode & 0o222:
            raise ArchiveError(f'refusing to change permissions on a writable hard link: {path}')
    return entries


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                            env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    if result.returncode:
        raise ArchiveError(result.stderr.strip() or 'could not inspect archive Git state')
    return result.stdout.strip()


def protect(root, check=False):
    if not root.exists() and not root.is_symlink():
        return 'no local archive; nothing to protect'
    if os.geteuid() == 0:
        raise ArchiveError('run as the archive owner, not root; root bypasses ordinary write permissions')
    entries = archive_entries(root)
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
        raise ArchiveError('archive is not its own Git working tree')
    if git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise ArchiveError('archive has uncommitted files; preserve and resolve them before protection')
    writable = [path for path in entries if path.lstat().st_mode & 0o222 or os.access(path, os.W_OK)]
    if check:
        if writable:
            raise ArchiveError(f'archive still has {len(writable)} writable entries; run mise run archive-protect')
        return f'archive is read-only ({len(entries)} entries)'
    for path in writable:
        path.chmod(stat.S_IMODE(path.lstat().st_mode) & ~0o222)
    if any(os.access(path, os.W_OK) or path.lstat().st_mode & 0o222 for path in entries):
        raise ArchiveError('some archive entries remain writable; inspect filesystem ACLs before treating it as protected')
    return f'protected archive: {len(writable)} entries made read-only; contents and read/execute permissions retained'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='verify protection without changing permissions')
    parser.add_argument('--archive', type=Path, default=Path(__file__).resolve().parents[1]/'.private',
                        help='archive directory (default: this checkout\'s .private)')
    args = parser.parse_args()
    try:
        print(protect(args.archive.absolute(), args.check))
    except (ArchiveError, OSError) as error:
        print(f'archive protection: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
