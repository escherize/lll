"""lll reads its environment once and never writes it (LLL-486).

Configuration is one value: config.read_env reads the process environment,
config.resolve layers it over the config files and the flags, and main passes
the result down. This test keeps it that way:

- no os.Setenv, os.Unsetenv or os.Clearenv (or their syscall twins) anywhere
  in src/ (tests included) or in the Go packages lll embeds. Writing the
  environment is how --team, tokens and admin credentials used to travel, and
  every child process (gh, git, a browser opener) inherited them;
- no os.Getenv, os.LookupEnv, os.Environ, os.ExpandEnv or os.UserHomeDir (or
  syscall.Getenv/Environ) outside config.read_env. A second reader is a
  second, hidden input that tests cannot set without mutating shared state;
- no `.Env = ...` on a command outside tests: a child gets the environment
  lll's parent gave it, not one lll composed. (A test may build a hermetic
  environment for a child it runs.)

`//` comments are skipped, outside string literals, so prose may name the
calls. ALLOW lists deliberate exceptions as {(path, call): reason}; it is
empty, and an entry must say why the value cannot come from Settings.
"""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

WRITES = re.compile(r'\b(?:os|syscall)\.(Setenv|Unsetenv|Clearenv)\s*\(')
READS = re.compile(r'\b(?:os|syscall)\.(Getenv|LookupEnv|Environ|ExpandEnv|UserHomeDir)\s*\(')
CHILD_ENV = re.compile(r'\.(Env)\s*=(?!=)')
# An aliased os or syscall import would hide every call above.
ALIASED = re.compile(r'^\s*import\s+(\w+)\s+"(?:go:)?(os|syscall)"|^\s*(\w+)\s+"(os|syscall)"\s*$', re.M)

# The one reader: this function in this file.
READER_FILE = 'src/config/config.lis'
READER_FN = 'read_env'

# (relative path, call) -> reason. Empty: no exception is needed.
ALLOW: dict[tuple[str, str], str] = {}


def strip_comments(source):
    """Source with `//` comments blanked, line numbers kept. A `//` inside a
    string literal ("http://...") is text, not a comment."""
    out = []
    for line in source.split('\n'):
        in_str, i, cut = False, 0, len(line)
        while i < len(line):
            c = line[i]
            if in_str:
                if c == '\\':
                    i += 2
                    continue
                if c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif line.startswith('//', i):
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return '\n'.join(out)


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


def is_test(rel):
    return rel.endswith('.test.lis') or rel.endswith('_test.go')


def violations(rel, source):
    """[(rel, line, call, kind)] for every env access `rel` may not make."""
    code = strip_comments(source)
    allowed_reads = fn_span(code, READER_FN) if rel == READER_FILE else None
    out = []

    def add(pos, call, kind):
        if (rel, call) not in ALLOW:
            out.append((rel, code.count('\n', 0, pos) + 1, call, kind))

    for kind, pattern in (('write', WRITES), ('read', READS)):
        for m in pattern.finditer(code):
            if kind == 'read' and allowed_reads and allowed_reads[0] <= m.start() < allowed_reads[1]:
                continue
            add(m.start(), m.group(0).split('(')[0].strip(), kind)
    if not is_test(rel):
        for m in CHILD_ENV.finditer(code):
            add(m.start(), '.Env =', 'child env')
    for m in ALIASED.finditer(code):
        add(m.start(), 'aliased ' + (m.group(2) or m.group(4)), 'alias')
    return out


def sources():
    for path in sorted((ROOT / 'src').rglob('*.lis')):
        yield path
    # Every Go file lll compiles in (gopb, pb, web, skills): tracked, not tests.
    listed = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '*.go'],
                            capture_output=True, text=True, check=True).stdout.split()
    for rel in sorted(listed):
        if rel.endswith('_test.go') or rel.startswith('scripts/'):
            continue
        yield ROOT / rel


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
        def calls(rel, text):
            return [(c, k) for _, _, c, k in violations(rel, text)]

        planted = 'fn x() {\n  let _ = os.Setenv("A", "b")\n  let y = os.Getenv("A")\n}\n'
        self.assertEqual(calls('src/x.lis', planted), [('os.Setenv', 'write'), ('os.Getenv', 'read')])
        # A comment naming a call is prose, not a call ...
        self.assertEqual(violations('src/x.lis', '// os.Setenv("A", "b")\n'), [])
        # ... but a url in a string does not start a comment.
        self.assertEqual(calls('src/x.lis', 'foo("http://h", os.Getenv("X"))\n'), [('os.Getenv', 'read')])
        self.assertEqual(calls('gopb/x.go', 'v := syscall.Getenv("X")\n'), [('syscall.Getenv', 'read')])
        self.assertEqual(calls('src/x.lis', 'cmd.Env = ["A=b"]\n'), [('.Env =', 'child env')])
        self.assertEqual(violations('src/x.test.lis', 'cmd.Env = ["A=b"]\n'), [])
        self.assertEqual(calls('gopb/x.go', 'import (\n\tgoos "os"\n)\n'), [('aliased os', 'alias')])
        # The reader may read, and only inside read_env.
        reader = 'pub fn read_env() -> Env {\n  Env { url: os.Getenv("LLL_URL") }\n}\nfn other() { os.Getenv("B") }\n'
        self.assertEqual([(line, c) for _, line, c, _ in violations(READER_FILE, reader)], [(4, 'os.Getenv')])
        # And even read_env may not write.
        writer = 'pub fn read_env() -> Env {\n  os.Setenv("A", "b")\n}\n'
        self.assertEqual(len(violations(READER_FILE, writer)), 1)


if __name__ == '__main__':
    unittest.main()
