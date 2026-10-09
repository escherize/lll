"""Every state change goes through models.transition (LLL-685).

Claim and state rules were spread over close, update, the board and the
server, and drifted: close released the claim and update --state done did
not. src/models/transition.lis is now the one rule on the client side, and
the write layer takes only the Effects it returns. Every record write is in
src/writes/ already (test_write_layer.py), so this test holds the rest:

- an Effects value is built only in src/models/transition.lis (its fields
  are private, so the compiler refuses one built outside models; this keeps
  the rest of models out too);
- IssuePatch.state is an Option<models.Effects>, and the one wire field
  that carries a state change, IssueFields.state, is filled from it;
- the close route's write takes the Effects of a close;
- no other struct in src/writes/ or src/models/ puts a `state` on the wire,
  except the ones in WIRE_STATE_ALLOWED, each with its reason.

`//` comments are skipped. Tests are skipped: they may build fixtures.
"""
from pathlib import Path
import re
import unittest

from test_write_layer import strip_comments

ROOT = Path(__file__).resolve().parents[1]

TRANSITION = 'src/models/transition.lis'
EFFECTS_LITERAL = re.compile(r'(?<![A-Za-z_])Effects\s*\{')
DECLARATION = re.compile(r'\b(struct|impl)\s+Effects\s*\{')

# (file, struct) -> why that struct may carry a state on the wire.
WIRE_STATE_ALLOWED = {
    ('src/writes/issues.lis', 'IssueFields'): 'the update wire body; its state is filled from the patch Effects (checked below)',
    ('src/models/models.lis', 'Issue'): 'the record as read, never sent as an update',
    ('src/models/models.lis', 'NewIssue'): 'a new issue starts in a state; there is no claim yet to transition',
}

STRUCT = re.compile(r'(?:pub\s+)?struct\s+(\w+)\s*\{(.*?)\n\}', re.S)
STATE_FIELD = re.compile(r'^\s*(?:#\[json\("state"[^\n]*\n\s*)?(?:pub\s+)?(state\w*)\s*:', re.M)
JSON_STATE = re.compile(r'#\[json\("state"')
FIELDS_FROM_EFFECTS = 'state: patch.state.map(|e| e.state().wire())'


def sources(root, prefixes):
    for path in sorted((root / 'src').rglob('*.lis')):
        rel = path.relative_to(root).as_posix()
        if rel.endswith('.test.lis') or not rel.startswith(prefixes):
            continue
        yield rel, strip_comments(path.read_text())


def effects_built_outside(files):
    found = []
    for rel, text in files:
        if rel == TRANSITION:
            continue
        for m in EFFECTS_LITERAL.finditer(text):
            line_start = text.rfind('\n', 0, m.start()) + 1
            if DECLARATION.search(text[line_start:m.end()]):
                continue
            found.append(f'{rel}:{text.count(chr(10), 0, m.start()) + 1}: builds Effects; only models.transition may')
    return found


def wire_states(files):
    """Structs that put a field named state on the wire, outside the allowlist."""
    found = []
    for rel, text in files:
        for m in STRUCT.finditer(text):
            name, body = m.group(1), m.group(2)
            wire = any(f.group(1) == 'state' for f in STATE_FIELD.finditer(body)) or JSON_STATE.search(body)
            if not wire or (rel, name) in WIRE_STATE_ALLOWED:
                continue
            # A struct holding the planned Effects is the patch, not the wire.
            if re.search(r'\bstate\s*:\s*Option<models\.Effects>', body):
                continue
            found.append(f'{rel}: struct {name} carries a state; take models.Effects, or add it to WIRE_STATE_ALLOWED with the reason')
    return found


def issue_fields_state(text):
    """The IssueFields.state assignments in src/writes/issues.lis."""
    return [line.strip().rstrip(',') for line in text.split('\n')
            if re.match(r'\s*state:\s', line) and 'Option<' not in line]


class TransitionRatchetTest(unittest.TestCase):
    def test_effects_are_built_only_by_the_transition(self):
        found = effects_built_outside(sources(ROOT, ('src/',)))
        self.assertEqual(found, [], '\n'.join(found))

    def test_no_state_on_the_wire_except_from_effects(self):
        found = wire_states(sources(ROOT, ('src/writes/', 'src/models/')))
        self.assertEqual(found, [], '\n'.join(found))

    def test_the_update_and_close_writes_take_effects(self):
        issues = (ROOT / 'src/writes/issues.lis').read_text()
        self.assertRegex(issues, r'pub state: Option<models\.Effects>,')
        self.assertEqual(issue_fields_state(issues), [FIELDS_FROM_EFFECTS])
        claims = (ROOT / 'src/writes/claims.lis').read_text()
        close = re.search(r'pub fn close_issue\((.*?)\)\s*->', claims, re.S)
        self.assertIsNotNone(close, 'writes.close_issue is gone; the close route must still take Effects')
        self.assertIn('effects: models.Effects', close.group(1))

    def test_the_check_sees_a_planted_bypass(self):
        planted = [('src/commands/x.lis', 'let e = models.Effects { asked, effect }'),
                   ('src/models/models.lis', 'fn f() -> Effects { Effects { asked: a, effect: e } }')]
        for rel, source in planted:
            self.assertTrue(effects_built_outside([(rel, source)]), source)
        self.assertFalse(effects_built_outside([(TRANSITION, 'Ok(Effects { asked, effect })')]))
        self.assertFalse(effects_built_outside([('src/models/x.lis', 'pub struct Effects {\n  asked: Ask,\n}\nimpl Effects {\n}')]))
        wire = [('src/writes/x.lis', '#[json]\nstruct StateFields {\n  state: string,\n}'),
                ('src/models/x.lis', '#[json]\npub struct Move {\n  #[json("state")]\n  pub to: string,\n}')]
        for rel, source in wire:
            self.assertTrue(wire_states([(rel, source)]), source)
        self.assertFalse(wire_states([('src/writes/x.lis', 'pub struct IssuePatch {\n  pub state: Option<models.Effects>,\n}')]))
        self.assertEqual(issue_fields_state('    state: patch.state.map(|e| e.state().wire()),\n  state: Option<string>,'),
                         [FIELDS_FROM_EFFECTS])
        self.assertNotEqual(issue_fields_state('    state: Some("done"),'), [FIELDS_FROM_EFFECTS])


if __name__ == '__main__':
    unittest.main()
