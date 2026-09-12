"""Export failure boundaries: real filesystem, controlled CLI responses."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

loader = importlib.machinery.SourceFileLoader('lll_export', str(Path(__file__).resolve().parents[1] / 'bin/lll-export'))
spec = importlib.util.spec_from_loader(loader.name, loader)
exporter = importlib.util.module_from_spec(spec)
loader.exec_module(exporter)


def issue(n):
    return {'id': str(n), 'number': n, 'expand': {'team': {'key': 'EXP'}}}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'mirror'
        self.issues = [issue(1)]
        self.docs = [{'slug': 'evidence'}]
        self.calls = []
        self.failure = None
        self.body = 'original'
        self.patch = mock.patch.object(exporter, 'command', side_effect=self.cli)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def cli(self, binary, *args):
        self.calls.append(args)
        if self.failure and self.failure(args):
            raise exporter.ExportError('injected CLI failure')
        if args[:2] == ('issue', 'list'):
            page = int(args[args.index('--page') + 1])
            return json.dumps({'items': self.issues[(page-1)*200:page*200], 'totalItems': len(self.issues),
                'totalPages': (len(self.issues)+199)//200, 'page': page}).encode()
        if args[:2] == ('doc', 'list'):
            return json.dumps({'items': self.docs}).encode()
        return f'# {args[-1]}\n\n{self.body}\n'.encode()

    def tree(self):
        return {str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob('*') if p.is_file()}

    def test_all_pages_and_removed_records(self):
        self.issues = [issue(n) for n in range(1, 402)]
        self.assertEqual(exporter.export('lll', self.target), (401, 1))
        self.assertEqual(len(list((self.target/'issues').iterdir())), 401)
        self.assertTrue((self.target/'issues/EXP-401.md').is_file())
        exporter.validate_mirror(self.target)
        self.issues = []
        self.docs = []
        self.assertEqual(exporter.export('lll', self.target), (0, 0))
        self.assertEqual(list((self.target/'issues').iterdir()), [])

    def test_failures_never_change_previous_mirror(self):
        exporter.export('lll', self.target)
        before = self.tree()
        self.issues = [issue(n) for n in range(1, 202)]
        self.body = 'new'
        for failure in [lambda a: a[:2] == ('doc', 'list'),
                        lambda a: a[:2] == ('issue', 'list') and a[-1] == '2',
                        lambda a: a[:2] == ('issue', 'view'),
                        lambda a: a[:2] == ('doc', 'view')]:
            self.failure = failure
            with self.assertRaises(exporter.ExportError):
                exporter.export('lll', self.target)
            self.assertEqual(self.tree(), before)

    def test_edited_and_unexpected_files_are_not_discarded(self):
        exporter.export('lll', self.target)
        for name in ['notes.txt', 'issues/unrelated.md', 'issues/EXP-1.md']:
            with self.subTest(name=name):
                p = self.target/name
                original = p.read_bytes() if p.exists() else None
                p.write_text('my work')
                with self.assertRaises(exporter.ExportError):
                    exporter.export('lll', self.target)
                self.assertEqual(p.read_text(), 'my work')
                if original is None:
                    p.unlink()
                else:
                    p.write_bytes(original)

    def test_unmanaged_and_symlink_targets_are_refused(self):
        self.target.mkdir()
        (self.target/'notes').write_text('keep')
        with self.assertRaises(exporter.ExportError):
            exporter.export('lll', self.target)
        link = self.root/'link'
        link.symlink_to(self.target, target_is_directory=True)
        with self.assertRaises(exporter.ExportError):
            exporter.destination(str(link))
        for path in ['/', '.', str(Path.cwd().parent), str(Path.home())]:
            with self.assertRaises(exporter.ExportError):
                exporter.destination(path)
        self.assertEqual((self.target/'notes').read_text(), 'keep')

    def test_publication_failure_rolls_back(self):
        exporter.export('lll', self.target)
        before = self.tree()
        rename = Path.rename
        def refuse_stage(path, destination):
            if '.lll-stage-' in str(path):
                raise OSError('publication refused')
            return rename(path, destination)
        self.body = 'new'
        with mock.patch.object(Path, 'rename', refuse_stage):
            with self.assertRaises(OSError):
                exporter.export('lll', self.target)
        self.assertEqual(self.tree(), before)

    def test_interrupted_publication_is_recovered_before_fetch(self):
        exporter.export('lll', self.target)
        before = self.tree()
        self.target.rename(self.root/'.mirror.lll-previous')
        self.failure = lambda _: True
        with self.assertRaises(exporter.ExportError):
            exporter.export('lll', self.target)
        self.assertEqual(self.tree(), before)

    def test_filesystem_aliases_cannot_overwrite_an_export(self):
        exporter.export('lll', self.target)
        before = self.tree()
        probe = self.root/'case-probe'
        probe.touch()
        insensitive = (self.root/'CASE-PROBE').exists()
        self.docs = [{'slug': 'Case'}, {'slug': 'case'}]
        if insensitive:
            with self.assertRaises(FileExistsError):
                exporter.export('lll', self.target)
            self.assertEqual(self.tree(), before)
        else:
            exporter.export('lll', self.target)
            self.assertEqual(len(list((self.target/'docs').iterdir())), 2)
        exporter.validate_mirror(self.target)

    def test_lock_and_filename_boundaries(self):
        with exporter.publication_lock(self.target):
            with self.assertRaises(exporter.ExportError):
                exporter.export('lll', self.target)
        for name in ['../escape', 'a/b', 'a\\b', '.', '..', '', 'a\0b']:
            with self.assertRaises(exporter.ExportError):
                exporter.filename(name)
        self.docs = [{'slug': 'duplicate'}, {'slug': 'duplicate'}]
        with self.assertRaises(exporter.ExportError):
            exporter.export('lll', self.target)
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
