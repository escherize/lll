#!/usr/bin/env python3
"""Package an existing Linux release binary without recompiling it."""
import argparse
import datetime
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

APP_ID = 'io.github.escherize.lll'
RUNTIME = '25.08'
MACHINES = {'x86_64': 62, 'aarch64': 183}
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--arch', choices=MACHINES, required=True)
    parser.add_argument('--version', required=True, help='Release version without v')
    parser.add_argument('--date', type=datetime.date.fromisoformat, required=True,
                        help='Release date, YYYY-MM-DD')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?', args.version):
        parser.error('version must be a semantic release version without v')
    binary = args.binary.resolve()
    with binary.open('rb') as source:
        header = source.read(20)
    if (len(header) != 20 or header[:6] != b'\x7fELF\x02\x01'
            or int.from_bytes(header[18:20], 'little') != MACHINES[args.arch]):
        parser.error(f'binary must be a 64-bit little-endian Linux ELF for {args.arch}')
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        parser.error(f'output already exists: {output}')

    def run(*command):
        subprocess.run(command, check=True)

    with tempfile.TemporaryDirectory(prefix='lll-flatpak-') as directory:
        base = Path(directory)
        build = base / 'build'
        repo = base / 'repo'
        # There is no compilation: the Platform itself supplies the build
        # environment, avoiding an unnecessary SDK download for binary packaging.
        run('flatpak', 'build-init', '--arch=' + args.arch, str(build), APP_ID,
            'org.freedesktop.Platform', 'org.freedesktop.Platform', RUNTIME)
        files = build / 'files'
        (files / 'bin').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binary, files / 'bin/lll')
        (files / 'bin/lll').chmod(0o755)
        meta = files / 'share/metainfo'
        meta.mkdir(parents=True)
        template = (ROOT / 'packaging/flatpak' / (APP_ID + '.metainfo.xml.in')).read_text()
        (meta / (APP_ID + '.metainfo.xml')).write_text(
            template.replace('@VERSION@', args.version).replace('@DATE@', args.date.isoformat()))
        licenses = files / 'share/licenses' / APP_ID
        licenses.mkdir(parents=True)
        shutil.copyfile(ROOT / 'LICENSE', licenses / 'LICENSE')
        run('flatpak', 'build-finish', '--command=lll', '--share=network', str(build))
        run('flatpak', 'build-export', '--arch=' + args.arch, str(repo), str(build), 'stable')
        run('flatpak', 'build-bundle', '--arch=' + args.arch,
            '--runtime-repo=https://flathub.org/repo/flathub.flatpakrepo',
            str(repo), str(output), APP_ID, 'stable')
    print(f'Built {output}')


if __name__ == '__main__':
    main()
