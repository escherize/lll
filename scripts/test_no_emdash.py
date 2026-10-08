"""lll's own voice has no em-dashes (LLL-650, decision D4 in v1-0-plan).

An em-dash (U+2014) is the strongest tell of generated prose, and every string
lll prints ends up pasted into a doc that the de-slop checker then fails. This
test fails on U+2014, or an HTML entity or escape that renders as one,
wherever lll speaks to a user:

- string literals in src/ (.lis), gopb/ and web/ (.go): help text, runtime
  messages and the board's server-rendered copy. Comments are skipped, and so
  are test files, which assert output rather than produce it;
- web/templates: the board's copy;
- the embedded skills under skills/;
- README.md and docs/index.html.

ALLOW lists deliberate exceptions as {(path, line text): reason}. Keep it
short: each entry must say why the dash is not lll's own voice.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Spelled as an escape so this file does not carry the character it hunts.
DASH = chr(0x2014)
DASHES = re.compile(DASH + r'|&mdash;|&#8212;|&#x2014;|\\u2014|\\u\{2014\}', re.IGNORECASE)

# (relative path, stripped line) -> reason. Empty: no exception is needed yet.
ALLOW: dict[tuple[str, str], str] = {}


def lis_literals(source):
    """(line, text) for each "..." literal in a .lis file, `//` comments skipped.

    f-string braces may nest quoted strings; their text counts too.
    """
    out = []
    i, n = 0, len(source)
    while i < n:
        if source.startswith('//', i):
            i = source.find('\n', i)
            if i < 0:
                break
            continue
        if source[i] == '"':
            i = read_lis_string(source, i, out)
            continue
        if source[i] == "'":
            # A char literal such as '"' must not open a string, but its
            # text still counts: '@' prints as surely as "@".
            end = source.find("'", i + 2)
            if 0 < end - i <= 4:
                out.append((source.count('\n', 0, i) + 1, source[i + 1:end]))
                i = end + 1
                continue
        i += 1
    return out


def is_prefixed(source, i, prefix):
    """Is the quote at source[i] preceded by the literal prefix, not an identifier?"""
    before = source[i - 2:i - 1]
    return source[i - 1:i] == prefix and not (before.isalnum() or before == '_')


def read_lis_string(source, i, out):
    """Read the literal opening at source[i]; return the index past it.

    Only an f-string's braces hold code, so only there can a quote open a
    nested string rather than close this one.
    """
    line = source.count('\n', 0, i) + 1
    if is_prefixed(source, i, 'r'):
        # A raw string has no escapes: r"\" is one backslash, then the close.
        end = source.find('"', i + 1)
        end = len(source) if end < 0 else end
        out.append((line, source[i + 1:end]))
        return end + 1
    fstring = is_prefixed(source, i, 'f')
    i += 1
    text = []
    depth = 0
    while i < len(source):
        ch = source[i]
        if ch == '\\':
            text.append(source[i:i + 2])
            i += 2
            continue
        if depth == 0 and ch == '"':
            out.append((line, ''.join(text)))
            return i + 1
        if fstring and ch == '{':
            depth += 1
        elif ch == '}' and depth > 0:
            depth -= 1
        elif ch == '"' and depth > 0:
            i = read_lis_string(source, i, out)
            continue
        text.append(ch)
        i += 1
    out.append((line, ''.join(text)))
    return i


def go_literals(source):
    """(line, text) for each "..." and `...` literal in Go, comments skipped."""
    out = []
    i, n = 0, len(source)
    while i < n:
        if source.startswith('//', i):
            i = source.find('\n', i)
            if i < 0:
                break
            continue
        if source.startswith('/*', i):
            i = source.find('*/', i + 2)
            if i < 0:
                break
            i += 2
            continue
        ch = source[i]
        if ch == "'":
            j = i + 1
            while j < n and source[j] != "'":
                j += 2 if source[j] == '\\' else 1
            out.append((source.count('\n', 0, i) + 1, source[i + 1:j]))
            i = j + 1
            continue
        if ch in '"`':
            line = source.count('\n', 0, i) + 1
            j = i + 1
            while j < n and source[j] != ch:
                j += 2 if ch == '"' and source[j] == '\\' else 1
            out.append((line, source[i + 1:j]))
            i = j + 1
            continue
        i += 1
    return out


def literal_hits(path, literals):
    rel = str(path.relative_to(ROOT))
    lines = path.read_text().splitlines()
    hits = []
    for line, text in literals:
        # A multi-line literal reports each line a dash is on.
        for offset, part in enumerate(text.split('\n')):
            if DASHES.search(part):
                hits.append((rel, line + offset, lines[line + offset - 1].strip()))
    return hits


def file_hits(path):
    rel = str(path.relative_to(ROOT))
    return [(rel, n, text.strip())
            for n, text in enumerate(path.read_text().splitlines(), 1) if DASHES.search(text)]


def all_hits():
    hits = []
    for path in sorted((ROOT / 'src').rglob('*.lis')):
        if not path.name.endswith('.test.lis'):
            hits += literal_hits(path, lis_literals(path.read_text()))
    for directory in ('gopb', 'web'):
        for path in sorted((ROOT / directory).rglob('*.go')):
            if not path.name.endswith('_test.go'):
                hits += literal_hits(path, go_literals(path.read_text()))
    for path in sorted((ROOT / 'web' / 'templates').rglob('*.html')):
        hits += file_hits(path)
    for path in sorted((ROOT / 'skills').rglob('*.md')):
        hits += file_hits(path)
    for rel in ('README.md', 'docs/index.html'):
        hits += file_hits(ROOT / rel)
    return [h for h in hits if (h[0], h[2]) not in ALLOW]


def dashed(text):
    """The sources below write the dash as @ so this file stays free of it."""
    return text.replace('@', DASH)


class NoEmDash(unittest.TestCase):
    def test_no_em_dash_in_user_facing_text(self):
        hits = all_hits()
        report = '\n'.join(f'{rel}:{n}: {text}' for rel, n, text in hits)
        self.assertEqual(hits, [], f'U+2014 in user-facing text (LLL-650):\n{report}')

    def test_lis_scanner_reads_literals_and_skips_comments(self):
        lis = dashed('fn f() {\n  // a @ comment\n  let s = f"x {g("a@b")}"\n'
                     '  let c = \'"\'\n  let j = "{\\"k\\":" + v + "@}"\n  "ok @"\n}\n')
        found = [t for _, t in lis_literals(lis) if DASHES.search(t)]
        self.assertEqual(found, dashed('a@b|@}|ok @').split('|'))

    def test_lis_scanner_raw_strings_and_chars(self):
        # r"\" ends at its second quote; reading \" as an escape would put
        # every later literal in the file inside out.
        lis = dashed('let b = r"\\"\nlet s = f"\'{x}\' @ y"\nlet c = \'@\'\n')
        found = [(n, t) for n, t in lis_literals(lis) if DASHES.search(t)]
        self.assertEqual(found, [(2, dashed("'{x}' @ y")), (3, dashed('@'))])

    def test_go_scanner_reads_literals_and_skips_comments(self):
        go = dashed('x := "a @" // b @\n/* c @ */ y := `d\n@`\nr := \'"\'\nq := \'@\'\n')
        found = [(n, t) for n, t in go_literals(go) if DASHES.search(t)]
        self.assertEqual(found, [(1, dashed('a @')), (2, dashed('d\n@')), (5, dashed('@'))])

    def test_entities_and_escapes_count_as_dashes(self):
        for text in ('401 &mdash; gated', '&#8212;', '&#X2014;', 'a \\u2014 b', '\\u{2014}'):
            self.assertTrue(DASHES.search(text), text)
        self.assertFalse(DASHES.search('a - b, c: d; e (f)'))

    def test_allow_list_entries_still_exist(self):
        for (rel, text), reason in ALLOW.items():
            self.assertTrue(reason, f'{rel}: allow-list entry needs a reason')
            lines = [l.strip() for l in (ROOT / rel).read_text().splitlines()]
            self.assertIn(text, lines, f'{rel}: stale allow-list entry')


if __name__ == '__main__':
    unittest.main()
