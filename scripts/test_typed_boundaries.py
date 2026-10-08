"""The typed pass holds (LLL-675).

The review behind LLL-675 found rules the code knew and its types did not
say: an empty team id meant "every team", errors carried their kind as a
control-character tag inside the text, and record ids of every collection
were interchangeable strings. Types now say each of those, and this test
keeps the strings from coming back, reading the sources of every non-test
.lis file:

- no function above the string-error boundaries returns Result<_, string>:
  errors are pb.CliError, so main reads a real kind for the exit code;
- record ids are made only by decoding (src/models) or in src/records and
  src/writes, never minted from a string in a command or a board handler;
- no parameter is a bare `team_id: string`: a team is a models.TeamId, and
  "every team" is query.TeamScope.Every, written out;
- the error tag machinery stays gone.

Boundaries that keep string errors: config (it reads files before pb
exists), gitctx (git's own output), and the modules that never fail
(markdown, models, references, theme, buildinfo, search, display,
provenance).
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
STRING_ERROR_BOUNDARIES = {'config', 'gitctx', 'markdown', 'models', 'references', 'theme', 'buildinfo',
                           'search', 'display', 'provenance'}
ID_MAKERS = {'models', 'records', 'writes'}
ID = r'(?:Team|Issue|Label|Project|Member|Claim)Id'


def module_of(rel):
    parts = rel.split('/')
    return parts[1] if len(parts) > 2 else 'main'


def sources(root=ROOT):
    """[(rel path, module, text)] for every non-test .lis file."""
    out = []
    for path in sorted((root / 'src').rglob('*.lis')):
        if path.name.endswith('.test.lis'):
            continue
        rel = path.relative_to(root).as_posix()
        out.append((rel, module_of(rel), path.read_text()))
    return out


def results_with_string_errors(text):
    """Each Result<T, string> in `text`, nested generics included."""
    found = []
    i = 0
    while True:
        j = text.find('Result<', i)
        if j < 0:
            return found
        k, depth, top = j + len('Result<'), 1, []
        start = k
        while depth:
            c = text[k]
            if c == '<':
                depth += 1
            elif c == '>' and text[k - 1] != '-':
                depth -= 1
            elif c == ',' and depth == 1:
                top.append(k)
            k += 1
        if top and text[top[-1] + 1:k - 1].strip() == 'string':
            found.append(text[j:k])
        i = start


def violations(files):
    found = []
    for rel, module, text in files:
        code = '\n'.join(l for l in text.split('\n') if not l.lstrip().startswith('//'))
        if module not in STRING_ERROR_BOUNDARIES:
            for r in results_with_string_errors(code):
                found.append(f'{rel}: {r}: errors above the boundaries are pb.CliError')
        if module not in ID_MAKERS:
            for m in re.finditer(r'(?<![\w.])(?:models\.)?' + ID + r'\(|\bas (?:models\.)?' + ID + r'\b', code):
                found.append(f'{rel}: {m.group(0)}: ids are decoded, or made in records/ or writes/')
        for m in re.finditer(r'\bteam_id: string\b', code):
            found.append(f'{rel}: team_id: string: a team is models.TeamId; every team is query.TeamScope.Every')
        for marker in ['pb.tag(', 'pb.classify(', 'pb.plain(', 'help_marker', 'filter_team(']:
            if marker in code:
                found.append(f'{rel}: {marker}: the string-tag and sentinel machinery is gone')
    return found


class TypedBoundariesTest(unittest.TestCase):
    def test_the_sources_hold_the_typed_boundaries(self):
        found = violations(sources())
        self.assertEqual(found, [], 'typed boundary broken (LLL-675):\n' + '\n'.join(found))

    def test_the_check_sees_planted_violations(self):
        planted = [
            ('src/commands/x.lis', 'commands', 'fn f() -> Result<int, string> { Ok(1) }'),
            ('src/serve/x.lis', 'serve', 'fn f() -> Result<Option<fn() -> Result<string, pb.CliError>>, string> { }'),
            ('src/serve/x.lis', 'serve', 'let id = models.LabelId(raw)'),
            ('src/commands/x.lis', 'commands', 'let id = raw as models.TeamId'),
            ('src/records/x.lis', 'records', 'fn fetch(ctx: pb.Client, team_id: string) {}'),
            ('src/commands/x.lis', 'commands', 'let t = scope.filter_team()'),
        ]
        for case in planted:
            self.assertTrue(violations([case]), case)
        clean = [
            ('src/config/x.lis', 'config', 'pub fn config(self) -> Result<Config, string> {}'),
            ('src/commands/x.lis', 'commands', 'fn f() -> Result<Map<string, string>, pb.CliError> {}'),
            ('src/records/x.lis', 'records', 'Some(models.MemberId(id))'),
            ('src/commands/x.lis', 'commands', '// a comment may say Result<int, string>'),
            ('src/serve/x.lis', 'serve', 'fn f(team_id: models.TeamId) {}'),
        ]
        self.assertEqual(violations(clean), [])


if __name__ == '__main__':
    unittest.main()
