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
  no string test or comparison on config.origin(...), no comparison with an
  origin literal;
- a match that names a config.Source has no arm that catches every source
  (`_`, a binding like `other`, `Some(_)`, `(other)` or a tuple of those
  such as `(_, _)`), so a new layer fails to
  compile in every hint until the hint says what fixes it;
- no `if let` picks one Source out, and no `==`/`!=` compares one, for the
  same reason.

config.origin is the one place an origin becomes a string, for printing.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = r'"(?:file:|env:|flag:)'
STRING_TESTS = re.compile(
    r'\b(?:HasPrefix|HasSuffix|TrimPrefix|TrimSuffix|CutPrefix|CutSuffix|Cut|starts_with|ends_with|contains|Contains'
    r'|Index|LastIndex|Split\w*|split|Fields|EqualFold|Count|Replace\w*)\(')
COMPARES = re.compile(
    r'(?:==|!=)\s*f?(?:' + ORIGIN + r'|"default")|f?(?:' + ORIGIN + r'[^"]*"|"default")\s*(?:==|!=)'
    # A printed origin compared with anything: compare the Source instead.
    r'|\borigin\([^()]*\)\s*(?:==|!=)|(?:==|!=)\s*(?:config\.)?origin\('
    # A Source compared with ==: a hidden one-variant `if let`.
    r'|(?:==|!=)\s*(?:Some\(\s*)?(?:config\.)?Source\.|\bSource\.\w+(?:\([^()]*\))?\)?\s*(?:==|!=)')
PICKS_ONE = re.compile(r'\bif let\b[^{]*\bSource\.')
NAMES_SOURCE = re.compile(r'\bSource\.|\b(?:Flag|Env|RepoFile|HomeFile)\(')


def sources(root=ROOT):
    """[(rel path, text)] for every non-test .lis file."""
    out = []
    for path in sorted((root / 'src').rglob('*.lis')):
        if path.name.endswith('.test.lis'):
            continue
        out.append((path.relative_to(root).as_posix(), path.read_text()))
    return out


def balanced(text, start):
    """The text from `start` (just past an opening paren or brace) to its match."""
    depth, k = 1, start
    while depth and k < len(text):
        depth += {'(': 1, '{': 1, ')': -1, '}': -1}.get(text[k], 0)
        k += 1
    return text[start:k - 1]


def without_strings(code):
    """`code` with every string literal emptied, so its braces and commas
    cannot be mistaken for code."""
    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)


def match_bodies(code):
    """The text between the braces of each `match ... {`, nested ones
    included, whether or not the brace is on the match's own line."""
    return [balanced(code, m.end()) for m in re.finditer(r'\bmatch\b[^{;]*\{', code)]


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


def split_top(text, sep):
    """`text` split at each `sep` outside parentheses and brackets."""
    parts, depth, cur = [], 0, []
    for c in text:
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        if c == sep and depth == 0:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append(''.join(cur))
    return parts


def catches_all(alt):
    """True for a pattern that matches every value: `_`, a binding such as
    `other`, or Some, parentheses or a tuple holding only those."""
    alt = alt.strip()
    if re.fullmatch(r'[a-z_]\w*', alt):
        return True
    inner = re.fullmatch(r'(?:Some\s*)?\((.*)\)', alt, re.S)
    return bool(inner) and all(catches_all(e) for e in split_top(inner.group(1), ','))


def arm_patterns(body):
    """The pattern of each arm of a match body."""
    return [arm.split('=>')[0].strip() for arm in split_top(top_level(body), ',') if '=>' in arm]


def violations(files):
    found = []
    for rel, text in files:
        code = '\n'.join(l for l in text.split('\n') if not l.lstrip().startswith('//'))
        for m in STRING_TESTS.finditer(code):
            args = balanced(code, m.end())
            if re.search(ORIGIN + r'|"\.lll\.toml"|\borigin\(', args):
                found.append(f'{rel}: {m.group(0)}{args}): match on config.Source, not on its printed form')
        for m in COMPARES.finditer(code):
            found.append(f'{rel}: {m.group(0)}: match on config.Source; do not compare it or its printed form')
        for m in PICKS_ONE.finditer(code):
            found.append(f'{rel}: {m.group(0)}: match every config.Source, so a new one must be handled')
        for body in match_bodies(without_strings(code)):
            patterns = arm_patterns(body)
            if not any(NAMES_SOURCE.search(p) for p in patterns):
                continue
            for p in patterns:
                if any(catches_all(alt) for alt in split_top(p, '|')):
                    found.append(f'{rel}: `{p} =>` in a match on config.Source catches every source; name each one')
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
            'match src.url {\n  Some(config.Source.Default) => 1,\n  Some(_) | None => 2,\n}',
            'match src.url {\n  Some(config.Source.Default) => 1,\n  other => 2,\n}',
            'match src.url {\n  Some(config.Source.Default) => { 1 },\n  _ => 2,\n}',
            'let x = match\n  src.url {\n  Some(config.Source.Default) => 1,\n  _ => 2,\n}',
            'if src.url == Some(config.Source.Default) {}',
            'if Source.Default != s {}',
            'if strings.HasPrefix(config.origin(src.url), "file:") {}',
            'if strings.HasSuffix(config.origin(src.url), ".lll.toml") {}',
            'if config.origin(src.url) == "default" {}',
            'match (src.url, src.token) {\n  (Some(config.Source.Default), _) => 1,\n  (_, _) => 2,\n}',
            'match src.url {\n  Some(config.Source.Default) => 1,\n  (other) => 2,\n}',
            'if strings.Index(config.origin(src.url), "file:") == Some(0) {}',
            'let parts = strings.SplitN(config.origin(src.url), ":", 2)',
        ]
        for code in planted:
            self.assertTrue(violations([('src/x/x.lis', code)]), code)
        clean = [
            'Some(Source.RepoFile(path)) | Some(Source.HomeFile(path)) => f"file:{path}",',
            'let path = filepath.Join(dir, ".lll.toml")',
            'if exists(".lll.toml") { return Some(".lll.toml") }',
            '// a comment may say strings.HasPrefix(origin, "file:")',
            'match src.url {\n  Some(config.Source.Default) => f"{a}, b",\n  Some(config.Source.Env(name)) | None => g(name, 1),\n}',
            'let from = if source.is_none() { "unset" } else { config.origin(source) }',
            'match (src.url, src.token) {\n  (Some(config.Source.Default), _) => 1,\n  (Some(config.Source.Env(n)), None) => 2,\n}',
            'match kind {\n  Kind.A => { match x { _ => 1 } },\n  _ => 2,\n}',
        ]
        self.assertEqual(violations([('src/x/x.lis', c) for c in clean]), [])


if __name__ == '__main__':
    unittest.main()
