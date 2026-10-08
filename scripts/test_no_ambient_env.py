"""lll reads its environment once and never writes it (LLL-486).

Configuration is one value: config.read_env reads the process environment,
config.resolve layers it over the config files and the flags, and main passes
the result down. This test keeps it that way:

- no os.Setenv, os.Unsetenv or os.Clearenv anywhere in src/ (tests included)
  or in gopb/'s server code. Writing the environment is how --team, tokens and
  admin credentials used to travel, and every child process (gh, git, a
  browser opener) inherited them;
- no os.Getenv, os.LookupEnv, os.Environ, os.ExpandEnv or os.UserHomeDir
  outside config.read_env. A second reader is a second, hidden input that
  tests cannot set without mutating shared state.

Comments are skipped, so prose may name the calls. ALLOW lists deliberate
exceptions as {(path, call): reason}; it is empty, and an entry must say why
the value cannot come from Settings.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

WRITES = re.compile(r'\bos\.(Setenv|Unsetenv|Clearenv)\s*\(')
READS = re.compile(r'\bos\.(Getenv|LookupEnv|Environ|ExpandEnv|UserHomeDir)\s*\(')

# The one reader: this function in this file.
READER_FILE = 'src/config/config.lis'
READER_FN = 'read_env'

# (relative path, call) -> reason. Empty: no exception is needed.
ALLOW: dict[tuple[str, str], str] = {}


def strip_comments(source):
    """Source with `//` comments blanked, line numbers kept. Good enough here:
    neither language puts `//` inside the calls this hunts."""
    return '\n'.join(re.sub(r'//.*$', '', line) for line in source.split('\n'))


def fn_span(source, name):
    """(start, end) offsets of `fn name`'s body in Lisette source, or None."""
    m = re.search(r'\bfn ' + re.escape(name) + r'\b[^{]*\{', source)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(source) and depth:
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
        i += 1
    return m.start(), i


def violations(rel, source):
    """[(rel, line, call, kind)] for every env access `rel` may not make."""
    code = strip_comments(source)
    allowed_reads = fn_span(code, READER_FN) if rel == READER_FILE else None
    out = []
    for kind, pattern in (('write', WRITES), ('read', READS)):
        for m in pattern.finditer(code):
            if kind == 'read' and allowed_reads and allowed_reads[0] <= m.start() < allowed_reads[1]:
                continue
            call = f'os.{m.group(1)}'
            if (rel, call) in ALLOW:
                continue
            out.append((rel, code.count('\n', 0, m.start()) + 1, call, kind))
    return out


def sources():
    for path in sorted((ROOT / 'src').rglob('*.lis')):
        yield path
    for path in sorted((ROOT / 'gopb').glob('*.go')):
        if not path.name.endswith('_test.go'):
            yield path


class NoAmbientEnvironment(unittest.TestCase):
    def test_nothing_reads_or_writes_the_environment_outside_read_env(self):
        found = []
        for path in sources():
            rel = path.relative_to(ROOT).as_posix()
            found += violations(rel, path.read_text(encoding='utf-8'))
        self.assertEqual(
            found, [],
            'environment access outside config.read_env (LLL-486); take the value from '
            'Settings instead, or add an ALLOW entry that says why it cannot:\n'
            + '\n'.join(f'  {rel}:{line}: {call} ({kind})' for rel, line, call, kind in found),
        )

    def test_the_one_reader_exists_and_reads(self):
        # If read_env moved or was renamed, the exemption above would silently
        # exempt nothing and every real read would fail: say so directly.
        code = strip_comments((ROOT / READER_FILE).read_text(encoding='utf-8'))
        span = fn_span(code, READER_FN)
        self.assertIsNotNone(span, f'{READER_FILE} has no fn {READER_FN}')
        self.assertIn('os.Getenv(', code[span[0]:span[1]])

    def test_the_scanner_catches_what_it_hunts(self):
        planted = 'fn x() {\n  let _ = os.Setenv("A", "b")\n  let y = os.Getenv("A")\n}\n'
        self.assertEqual(
            [(c, k) for _, _, c, k in violations('src/x.lis', planted)],
            [('os.Setenv', 'write'), ('os.Getenv', 'read')],
        )
        # A comment naming a call is prose, not a call.
        self.assertEqual(violations('src/x.lis', '// os.Setenv("A", "b")\n'), [])
        # The reader may read, and only inside read_env.
        reader = 'pub fn read_env() -> Env {\n  Env { url: os.Getenv("LLL_URL") }\n}\nfn other() { os.Getenv("B") }\n'
        self.assertEqual(
            [(line, c) for _, line, c, _ in violations(READER_FILE, reader)],
            [(4, 'os.Getenv')],
        )
        # And even read_env may not write.
        writer = 'pub fn read_env() -> Env {\n  os.Setenv("A", "b")\n}\n'
        self.assertEqual(len(violations(READER_FILE, writer)), 1)


if __name__ == '__main__':
    unittest.main()
