"""Settings carry their source as a type (LLL-687).

Where a setting came from used to be a string ("env:LLL_URL",
"file:<path>", "flag:--team", "default"), and each recovery hint took it
apart by prefix and suffix: a repo file was "a path ending in .lll.toml".
Hints patched one by one drifted, and an error told the user to run
'lll config set url' when the url came from LLL_URL or a repo file.

config.Source now names each layer, and every hint matches on it. This test
keeps the strings from coming back, reading every non-test .lis file:

- no origin is compared to, or taken apart as, a string: no "file:",
  "env:" or "flag:" in a prefix or suffix test, no ".lll.toml" suffix test,
  no comparison with an origin literal;
- a match that names a config.Source has no `_ =>` arm, so a new layer
  fails to compile in every hint until the hint says what fixes it;
- no `if let` picks one Source out, for the same reason.

config.origin is the one place an origin becomes a string, for printing.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = r'"(?:file:|env:|flag:)'
TAKES_APART = re.compile(
    r'(?:HasPrefix|HasSuffix|TrimPrefix|TrimSuffix|CutPrefix|CutSuffix|starts_with|ends_with|contains|Contains)'
    r'\([^)]*(?:' + ORIGIN + r'|"\.lll\.toml"\))')
COMPARES = re.compile(
    r'(?:==|!=)\s*f?(?:' + ORIGIN + r'|"default")|f?(?:' + ORIGIN + r'[^"]*"|"default")\s*(?:==|!=)')
PICKS_ONE = re.compile(r'\bif let\b[^{]*\bSource\.')


def sources(root=ROOT):
    """[(rel path, text)] for every non-test .lis file."""
    out = []
    for path in sorted((root / 'src').rglob('*.lis')):
        if path.name.endswith('.test.lis'):
            continue
        out.append((path.relative_to(root).as_posix(), path.read_text()))
    return out


def match_bodies(code):
    """The text between the braces of each `match ... {`, nested ones included."""
    bodies = []
    for m in re.finditer(r'\bmatch\b[^{\n]*\{', code):
        depth, k = 1, m.end()
        while depth and k < len(code):
            depth += {'{': 1, '}': -1}.get(code[k], 0)
            k += 1
        bodies.append(code[m.end():k - 1])
    return bodies


def top_level(body):
    """`body` with every nested brace block removed: the match's own arms."""
    out, depth = [], 0
    for c in body:
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif depth == 0:
            out.append(c)
    return ''.join(out)


def violations(files):
    found = []
    for rel, text in files:
        code = '\n'.join(l for l in text.split('\n') if not l.lstrip().startswith('//'))
        for m in TAKES_APART.finditer(code):
            found.append(f'{rel}: {m.group(0)}: match on config.Source, not on its printed form')
        for m in COMPARES.finditer(code):
            found.append(f'{rel}: {m.group(0)}: compare config.Source values, not origin strings')
        for m in PICKS_ONE.finditer(code):
            found.append(f'{rel}: {m.group(0)}: match every config.Source, so a new one must be handled')
        for body in match_bodies(code):
            arms = top_level(body)
            if 'Source.' in arms and re.search(r'(?:^|[,{(]|\s)_\s*=>', arms):
                found.append(f'{rel}: a match on config.Source has a `_ =>` arm; name every source')
    return found


class TypedSourcesTest(unittest.TestCase):
    def test_no_origin_is_a_string_again(self):
        found = violations(sources())
        self.assertEqual(found, [], 'setting sources typed (LLL-687):\n' + '\n'.join(found))

    def test_the_check_sees_planted_violations(self):
        planted = [
            'if strings.HasPrefix(origin, "file:") {}',
            'let path = strings.TrimPrefix(origin, "file:")',
            'if let Some(p) = strings.CutPrefix(s.token_source, "file:") {}',
            'if strings.HasSuffix(origin, ".lll.toml") {}',
            'if origin == "env:LLL_URL" {}',
            'if src.url != "default" {}',
            'if src.token == f"file:{home}" {}',
            'if "flag:--team" == origin {}',
            'if let Some(config.Source.RepoFile(path)) = src.token {}',
            'match src.url {\n  Some(config.Source.Default) => 1,\n  _ => 2,\n}',
        ]
        for code in planted:
            self.assertTrue(violations([('src/x/x.lis', code)]), code)
        clean = [
            'Some(Source.RepoFile(path)) | Some(Source.HomeFile(path)) => f"file:{path}",',
            'let path = filepath.Join(dir, ".lll.toml")',
            'if exists(".lll.toml") { return Some(".lll.toml") }',
            '// a comment may say strings.HasPrefix(origin, "file:")',
            'match src.url {\n  Some(config.Source.Default) => 1,\n  Some(_) | None => 2,\n}',
            'match kind {\n  Kind.A => { match x { _ => 1 } },\n  _ => 2,\n}',
        ]
        self.assertEqual(violations([('src/x/x.lis', c) for c in clean]), [])


if __name__ == '__main__':
    unittest.main()
