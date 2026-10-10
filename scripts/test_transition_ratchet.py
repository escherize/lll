"""Every state change goes through models.transition (LLL-685).

Claim and state rules were spread over close, update, the board and the
server, and drifted: close released the claim and update --state done did
not. Every record write is in src/writes/ already (test_write_layer.py);
this test holds that a state reaches the wire from src/writes/ only as a
planned transition:

- The type system does most of it. IssuePatch.state is an Effects, the
  update wire body's state is a models.StateWrite, and both have private
  fields, so outside src/models/ only models.transition makes an Effects and
  only Effects.write() makes a StateWrite. The compiler test plants the
  bypasses in a copy of the tree and expects `lis check` to fail on each.
- Inside src/models/ the privacy does not hold, so an Effects or StateWrite
  is built only in src/models/transition.lis.
- What the types cannot see is text and other structs:
  - No string literal in src/writes/ or src/pb/ (the client the layer sends
    through) may contain the word "state": a hand-written JSON body, a Map
    key, a json attribute.
  - src/writes/ builds no Map, whose keys are text a concatenation can hide.
  - Every struct in src/ that puts a state on the wire (a state field of any
    type but the planned ones, or a json attribute naming "state") is a
    state type. src/writes/ may name one only where STATE_TYPES_ALLOWED says
    why: NewIssue on the create path, the read Issue where it is decoded.
    A struct with an unplanned state field declared in src/writes/ itself
    fails outright.

This is a lint over source text, not a proof: a value of a state type can
still reach src/writes/ through a function that returns one without naming
the type. What enforces the claim rule is the server (gopb TransitionClaim,
read by /close and finishReleases); this test keeps the client from
growing a second way to set a state by accident.

`//` comments are skipped. Tests are skipped: they may build fixtures.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_write_layer import strip_comments

ROOT = Path(__file__).resolve().parents[1]

TRANSITION = 'src/models/transition.lis'
PRIVATE_LITERAL = re.compile(r'(?<![A-Za-z_])(Effects|StateWrite)\s*\{')
DECLARATION = re.compile(r'(\b(struct|impl)\s+|->\s*)(Effects|StateWrite)\s*\{$')

STRUCT = re.compile(r'(?:pub\s+)?struct\s+(\w+)\s*\{(.*?)\n\}', re.S)
STATE_FIELD = re.compile(r'^\s*(?:pub\s+)?state\s*:\s*([^,\n]*)', re.M | re.I)
PLANNED_TYPES = ('Option<models.Effects>', 'Option<models.StateWrite>')
JSON_STATE = re.compile(r'#\[json\(\s*"state"')
FN = re.compile(r'\bfn\s+(\w+)')
MAP = re.compile(r'\bMap\b')

# (qualified type, function in src/writes/) -> why that function may name it.
STATE_TYPES_ALLOWED = {
    ('models.NewIssue', 'create_issue'): 'the create path: a new issue starts in a state, with no claim to transition',
    ('models.NewIssue', 'create_issue_once'): 'the create path, with an idempotency key',
    ('models.Issue', 'update_issue'): 'the record as read; the update sends IssueFields, never the record',
    ('models.Issue', 'reread'): 'decoded from the server after a 412, never encoded',
}

STRING = re.compile(r'(?:\bf|\br)?"((?:[^"\\]|\\.)*)"')
STATE_WORD = re.compile(r'state', re.I)


def sources(root, prefixes):
    for path in sorted((root / 'src').rglob('*.lis')):
        rel = path.relative_to(root).as_posix()
        if rel.endswith('.test.lis') or not rel.startswith(prefixes):
            continue
        yield rel, strip_comments(path.read_text())


def built_outside(files):
    """Effects or StateWrite literals outside src/models/transition.lis."""
    found = []
    for rel, text in files:
        if rel == TRANSITION:
            continue
        for m in PRIVATE_LITERAL.finditer(text):
            line_start = text.rfind('\n', 0, m.start()) + 1
            if DECLARATION.search(text[line_start:m.end()]):
                continue
            found.append(f'{rel}:{text.count(chr(10), 0, m.start()) + 1}: builds {m.group(1)}; only models.transition may')
    return found


def state_fields(files):
    """Structs in src/writes/ with a state field that is not the planned one."""
    found = []
    for rel, text in files:
        for m in STRUCT.finditer(text):
            for f in STATE_FIELD.finditer(m.group(2)):
                if f.group(1).strip() not in PLANNED_TYPES:
                    found.append(f'{rel}: struct {m.group(1)} has state: {f.group(1).strip()}; take models.Effects')
    return found


def state_literals(files):
    """String literals in src/writes/ that name a state field."""
    found = []
    for rel, text in files:
        for m in STRING.finditer(text):
            if STATE_WORD.search(m.group(1)):
                found.append(f'{rel}:{text.count(chr(10), 0, m.start()) + 1}: string {m.group(0)[:60]} names a state; put a state on the wire only as models.Effects.write()')
    return found


def state_types(files):
    """{qualified name: (module, bare name)} for every struct that puts a state
    on the wire. A src/writes/ struct is named bare there, so its key is bare."""
    found = {}
    for rel, text in files:
        module = rel.split('/')[1]
        for m in STRUCT.finditer(text):
            body = m.group(2)
            unplanned = any(f.group(1).strip() not in PLANNED_TYPES for f in STATE_FIELD.finditer(body))
            if unplanned or JSON_STATE.search(body):
                name = m.group(1)
                found[name if module == 'writes' else f'{module}.{name}'] = (module, name)
    return found


def state_type_uses(files, types):
    """Names of a state type in src/writes/ outside STATE_TYPES_ALLOWED."""
    found = []
    for rel, text in files:
        for qualified, (module, name) in types.items():
            pattern = rf'(?<![\w.]){name}\b' if module == 'writes' else rf'\b{module}\.{name}\b'
            for m in re.finditer(pattern, text):
                fns = FN.findall(text, 0, m.start())
                fn = fns[-1] if fns else ''
                if (qualified, fn) in STATE_TYPES_ALLOWED:
                    continue
                line = text.count('\n', 0, m.start()) + 1
                found.append(f'{rel}:{line}: {fn or "top level"} names {qualified}, which carries a state; send IssueFields from a planned Effects, or add it to STATE_TYPES_ALLOWED with the reason')
    return found


def map_bodies(files):
    found = []
    for rel, text in files:
        for m in MAP.finditer(text):
            found.append(f'{rel}:{text.count(chr(10), 0, m.start()) + 1}: builds a Map; a write body is a struct')
    return found


class TransitionRatchetTest(unittest.TestCase):
    def test_effects_and_state_writes_are_built_only_by_the_transition(self):
        found = built_outside(sources(ROOT, ('src/',)))
        self.assertEqual(found, [], '\n'.join(found))

    def test_no_state_on_the_wire_except_a_planned_one(self):
        writes = list(sources(ROOT, ('src/writes/',)))
        types = state_types(sources(ROOT, ('src/',)))
        found = (state_fields(writes) + state_literals(list(sources(ROOT, ('src/writes/', 'src/pb/'))))
                 + map_bodies(writes) + state_type_uses(writes, types))
        self.assertEqual(found, [], '\n'.join(found))

    def test_the_state_types_are_the_known_ones(self):
        # If this list grows, the new type is one src/writes/ must not send.
        types = state_types(sources(ROOT, ('src/models/', 'src/writes/', 'src/pb/', 'src/claims/')))
        self.assertEqual(sorted(types), ['models.Issue', 'models.NewIssue'])

    def test_each_review_bypass_is_seen(self):
        # N1: a new struct with a state field, declared elsewhere and sent from writes.
        n1_types = state_types([('src/models/x.lis', 'pub struct Move {\n  pub state: string,\n}')])
        self.assertTrue(state_type_uses([('src/writes/x.lis', 'fn send() {\n  let body = encode(models.Move { state: s }, "m")?\n}')], n1_types))
        # N2: a Map body whose key is built so no literal says "state".
        self.assertTrue(map_bodies([('src/writes/x.lis', 'let mut body = Map.new<string, string>()\nbody["st" + "ate"] = "done"')]))
        # N3: the existing NewIssue, encoded and sent as a PATCH outside the create path.
        real = state_types(sources(ROOT, ('src/models/',)))
        self.assertTrue(state_type_uses([('src/writes/x.lis', 'fn finish(issue: models.NewIssue) {\n  let body = encode(issue, "issue")?\n}')], real))
        self.assertFalse(state_type_uses([('src/writes/x.lis', 'fn create_issue(issue: models.NewIssue) {\n}')], real))
        # N4: a helper in the HTTP client that sends a state.
        self.assertTrue(state_literals([('src/pb/client.lis', 'let _ = self.send_as(c, "PATCH", path, "{\\"state\\":\\"done\\"}", "application/json")')]))

    def test_the_update_and_close_writes_take_effects(self):
        issues = (ROOT / 'src/writes/issues.lis').read_text()
        self.assertRegex(issues, r'pub state: Option<models\.Effects>,')
        self.assertRegex(issues, r'\n  state: Option<models\.StateWrite>,')
        claims = (ROOT / 'src/writes/claims.lis').read_text()
        close = re.search(r'pub fn close_issue\((.*?)\)\s*->', claims, re.S)
        self.assertIsNotNone(close, 'writes.close_issue is gone; the close route must still take Effects')
        self.assertIn('effects: models.Effects', close.group(1))

    def test_the_text_checks_see_each_planted_bypass(self):
        self.assertTrue(built_outside([('src/models/models.lis', 'fn f() -> Effects { Effects { asked: a } }')]))
        self.assertTrue(built_outside([('src/models/models.lis', 'let w = StateWrite { wire: "done" }')]))
        self.assertFalse(built_outside([(TRANSITION, 'Effects { asked }')]))
        self.assertFalse(built_outside([('src/models/x.lis', 'pub struct Effects {\n  asked: Ask,\n}\nimpl StateWrite {\n}\npub fn write(self) -> StateWrite {')]))
        planted = {
            'a hand-written PATCH body': 'let _ = ctx.send_as(by.caller, "PATCH", path, "{\\"state\\": \\"done\\"}", "application/json")?',
            'a Map body': 'body["state"] = "done"',
            'a json attribute': '#[json("state", omitempty)]\n  to: Option<string>,',
            'an f-string': 'let body = f"{{\\"State\\":\\"{to}\\"}}"',
        }
        for what, source in planted.items():
            self.assertTrue(state_literals([('src/writes/x.lis', source)]), what)
        self.assertTrue(state_fields([('src/writes/x.lis', '#[json]\nstruct StateFields {\n  state: Option<string>,\n}')]))
        self.assertFalse(state_fields([('src/writes/x.lis', 'struct IssueFields {\n  state: Option<models.StateWrite>,\n}')]))
        self.assertFalse(state_literals([('src/writes/x.lis', '"issue fields"')]))

    @unittest.skipUnless(shutil.which('lis'), 'lis is not on PATH')
    def test_the_compiler_refuses_a_state_built_outside_the_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            for name in ('lisette.toml', 'src', 'gopb', 'web', 'pb', 'skills', 'docs'):
                source = ROOT / name
                if source.is_dir():
                    shutil.copytree(source, tree / name, ignore=shutil.ignore_patterns('pb_data', 'target'))
                else:
                    shutil.copy(source, tree / name)
            issues = tree / 'src/writes/issues.lis'
            text = issues.read_text()
            anchor = '    let mut routed = fields\n'
            self.assertIn(anchor, text)
            issues.write_text(text.replace(anchor, anchor + '    routed.state = Some("done")\n', 1))
            (tree / 'src/writes/zz_planted.lis').write_text(
                'import "models"\n\n'
                'fn planted_fields() -> IssueFields {\n'
                '  IssueFields { state: Some(models.StateWrite { wire: "done" }), .. }\n'
                '}\n\n'
                'fn planted_effects() -> models.Effects {\n'
                '  models.Effects { .. }\n'
                '}\n')
            out = subprocess.run(['lis', 'check'], cwd=tree, capture_output=True, text=True, timeout=600)
            report = re.sub(r'\x1b\[[0-9;]*m', '', out.stdout + out.stderr)
            self.assertNotEqual(out.returncode, 0, report[-2000:])
            line = text[:text.index(anchor)].count('\n') + 2
            for where in (f'src/writes/issues.lis:{line}:', 'src/writes/zz_planted.lis:4:', 'src/writes/zz_planted.lis:8:'):
                self.assertRegex(report, r'✕[^\n]*\n\s*╭─\[' + re.escape(where), f'no error at {where}:\n{report[-3000:]}')


if __name__ == '__main__':
    unittest.main()
