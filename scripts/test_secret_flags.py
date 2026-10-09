"""Every secret flag is a Secret, read one way (LLL-686).

Secrets were plain strings, and each flag read its own: --admin-password -
read stdin, member create's --password took "-" literally, --token - printed
its prompt into a pipe. src/secret now owns them. Its Secret keeps the value
in a private field, so the compiler refuses any other module the text; this
test holds the rest, reading every non-test .lis file:

- every secret flag a spec declares (a name or hint that says password,
  token or secret) is in SECRET_FLAGS, and SECRET_FLAGS is the list
  src/secret/secret.test.lis drives through '-' and a literal;
- each of them is read by Secret.read, and no code outside src/secret reads
  its raw value with .one() or .all(), on one line or several, nor calls
  .one()/.all() with a computed name in a file that declares one;
- reveal(), the one accessor that returns the text, is called only on the
  lines in REVEALS, each a request that sends the secret or a config write
  that saves it;
- Secret has no public field, and no public function of src/secret other
  than the listed ones returns text (string, byte or rune) or takes or
  returns a function, the ways a value could be handed out.

Known limits. Which flags are secret is a naming heuristic: a name with
password, passphrase, token, secret, credential or api-key in it, or a hint
of pw, token or SECRET. A secret flag named otherwise (--key HINT) is not
seen, and needs adding to SECRET_FLAGS by hand. The reveal allowlist is
per line text, so it cannot tell an allowed line moved to a print site in
the same file, or a revealed string printed after the allowed line; review
catches those. reflect can reach any value, and is not checked.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SECRET_FLAGS = {'--password', '--old-password', '--admin-password', '--token', '--secret'}
SECRET_WORD = re.compile(r'password|passphrase|token|secret|credential|api-?key', re.I)
REVEAL = re.compile(r'\breveal\b')
FLAG = re.compile(r'Flag\s*\{([^{}]*)\}')
NAME = re.compile(r'\bname:\s*"(--[a-z-]+)"')
HINT = re.compile(r'\bhint:\s*"([^"]*)"')
COMPUTED = re.compile(r'\.(?:one|all)\(\s*(?!["|)])')
# Functions of src/secret allowed to return text, and why: the constructor's
# Result holds a Secret, reveal is the audited door, string and go_string
# return the placeholder.
TEXT_OK = ('read', 'confirmed', 'reveal', 'string', 'go_string')

# (relative path, stripped line) -> where the text goes. Each line is allowed
# once per file. Keep it short: a new entry is a new place a secret leaves
# its type, and the PR adding it says why.
REVEALS = {
    ('src/commands/login.lis', 'let tok = strings.TrimSpace(given.reveal())'):
        '--token: sent to the access route, then saved to the home config',
    ('src/commands/login.lis', 'models.AuthRequest { identity: email, password: password.reveal() },'):
        'login: auth-with-password request',
    ('src/commands/login.lis', 'let _ = create_member_as(ctx, su, name, email, password.reveal(), [], None)?'):
        'login --create: member create request',
    ('src/commands/token.lis', 'if email != "" { return Ok(AdminLogin.Explicit(config.AdminCreds { email, password: pw.reveal() })) }'):
        '--admin-password: the credentials superuser_login sends',
    ('src/commands/member.lis', 'match create_member_as(ctx, ctx.token(), name, email, pw.reveal(), [], None) {'):
        'member create --password: member create request',
    ('src/commands/member_password.lis', 'old_password: Some(old.reveal()),'):
        'set-password --old-password: member update request',
    ('src/commands/member_password.lis', 'password: Some(password.reveal()),'):
        'set-password (own): member update request',
    ('src/commands/member_password.lis', 'password_confirm: Some(password.reveal()),'):
        'set-password (own): member update request',
    ('src/commands/member_password.lis', 'let payload = match json.Marshal(models.AuthRequest { identity: email, password: password.reveal() }) {'):
        'set-password (own): the re-login request',
    ('src/commands/member_password.lis', 'let mut patch = writes.MemberPatch { password: Some(password.reveal()), password_confirm: Some(password.reveal()), .. }'):
        'set-password (superuser): member update request',
    ('src/commands/webhook.lis', 'Some(s) => s.reveal(),'):
        'webhook add --secret: webhook create request',
}


def sources(root=ROOT):
    """[(rel path, text)] for every non-test .lis file."""
    out = []
    for path in sorted((root / 'src').rglob('*.lis')):
        if not path.name.endswith('.test.lis'):
            out.append((path.relative_to(root).as_posix(), path.read_text()))
    return out


def declared_secret_flags(files):
    """{flag name: [rel path]} for each spec flag whose name or hint names a secret."""
    found = {}
    for rel, text in files:
        for body in FLAG.findall(text):
            name = NAME.search(body)
            hint = HINT.search(body)
            hint = hint.group(1) if hint else ''
            if name and (SECRET_WORD.search(name.group(1)) or hint in ('pw', 'token', 'SECRET')):
                found.setdefault(name.group(1), []).append(rel)
    return found


def line_of(text, pos):
    return text.count('\n', 0, pos) + 1


def violations(files, reveals=REVEALS):
    found = []
    declared = declared_secret_flags(files)
    for name, where in sorted(declared.items()):
        if name not in SECRET_FLAGS:
            found.append(f'{name} ({", ".join(where)}) is a secret flag missing from SECRET_FLAGS and the secret tests')
    outside = [(rel, text) for rel, text in files if not rel.startswith('src/secret/')]
    for name in sorted(declared):
        raw = re.compile(r'\.(?:one|all)\(\s*"' + re.escape(name) + r'"')
        for rel, text in outside:
            for m in raw.finditer(text):
                found.append(f'{rel}:{line_of(text, m.start())}: reads {name} raw; use secret.Secret.read (or secret.from_stdin)')
        read = re.compile(r'Secret\.read\(\s*p,\s*"' + re.escape(name) + r'"')
        if not any(read.search(text) for _, text in files):
            found.append(f'{", ".join(declared[name])}: declares {name}, which nothing reads with secret.Secret.read')
    declaring = {rel for where in declared.values() for rel in where}
    for rel, text in outside:
        if rel in declaring:
            for m in COMPUTED.finditer(text):
                found.append(f'{rel}:{line_of(text, m.start())}: .one()/.all() with a computed flag name in a file with secret flags; name the flag')
    seen = set()
    for rel, text in files:
        if rel.startswith('src/secret/'):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if not REVEAL.search(line) or line.strip().startswith('//'):
                continue
            key = (rel, line.strip())
            if key not in reveals:
                found.append(f'{rel}:{n}: reveal outside the allowed send/save sites: {line.strip()}')
            elif key in seen:
                found.append(f'{rel}:{n}: a second copy of an allowed reveal line: {line.strip()}')
            seen.add(key)
    for rel, line in sorted(set(reveals) - seen):
        found.append(f'{rel}: allowed reveal no longer present, drop it from REVEALS: {line}')
    secret = dict(files).get('src/secret/secret.lis', '')
    if re.search(r'pub struct Secret\s*\{[^}]*\bpub\b', secret):
        found.append('src/secret/secret.lis: Secret has a public field')
    for name, params, ret in re.findall(r'pub fn (\w+)\s*\(([^{]*?)\)\s*(?:->\s*([^{]+))?\{', secret, re.S):
        if name in TEXT_OK:
            continue
        if re.search(r'string|byte|rune', ret or ''):
            found.append(f'src/secret/secret.lis: {name} returns text ({ret.strip()})')
        if re.search(r'\bfn\s*\(', params + (ret or '')):
            found.append(f'src/secret/secret.lis: {name} takes or returns a function')
    return found


def tested_flags(root=ROOT):
    text = (root / 'src/secret/secret.test.lis').read_text()
    body = re.search(r'fn secret_flags\(\) -> Slice<string> \{\s*\[([^\]]*)\]', text)
    return set(re.findall(r'"([^"]+)"', body.group(1))) if body else set()


class SecretFlagsTest(unittest.TestCase):
    def test_every_secret_flag_is_a_secret(self):
        found = violations(sources())
        self.assertEqual(found, [], 'secret flag rule broken:\n' + '\n'.join(found))

    def test_the_unit_tests_cover_every_secret_flag(self):
        self.assertEqual(tested_flags(), SECRET_FLAGS)

    def test_the_specs_still_declare_the_secret_flags(self):
        self.assertEqual(set(declared_secret_flags(sources())), SECRET_FLAGS)

    def test_the_check_sees_planted_violations(self):
        base = [
            ('src/secret/secret.lis', 'pub struct Secret { value: string }\npub fn reveal(self) -> string { self.value }'),
            ('src/commands/a.lis', 'flags.Flag { name: "--password", value: true, hint: "pw", .. }\n'
                                   'let s = secret.Secret.read(p, "--password", "", input)?'),
        ]
        self.assertEqual(violations(base, {}), [])
        planted = [
            [base[0], ('src/commands/a.lis', 'flags.Flag { name: "--password", value: true, hint: "pw", .. }')],
            [base[0], ('src/commands/a.lis', 'flags.Flag { name: "--password", value: true, hint: "pw", .. }\nlet s = p.one("--password")')],
            [base[0], base[1], ('src/commands/b.lis', 'flags.Flag { name: "--api-key", value: true, hint: "pw", .. }')],
            [base[0], base[1], ('src/commands/b.lis', 'flags.Flag { name: "--bot-token", value: true, hint: "x", .. }')],
            [base[0], base[1], ('src/commands/b.lis', 'fmt.Println(s.reveal())')],
            [('src/secret/secret.lis', 'pub struct Secret { pub value: string }'), base[1]],
            [('src/secret/secret.lis', 'pub fn text(self) -> string { self.value }'), base[1]],
            [('src/secret/secret.lis', 'pub fn bytes(s: Secret) -> Option<Slice<byte>> {'), base[1]],
            [base[0], base[1], ('src/commands/b.lis', 'fmt.Println(chosen.map_or("", secret.Secret.reveal))')],
        ]
        for files in planted:
            self.assertTrue(violations(files, {}), files)
        more = [
            [base[0], ('src/commands/a.lis', base[1][1] + '\nlet pw = p.one(\n  "--password",\n)')],
            [base[0], ('src/commands/a.lis', base[1][1] + '\nlet f = "--password"\nlet pw = p.one(f)')],
            [base[0], base[1], ('src/commands/b.lis', 'flags.Flag { hint: "pw", name: "--api-key", value: true, .. }')],
            [base[0], base[1], ('src/commands/b.lis', 'flags.Flag { name: "--passphrase", value: true, hint: "PHRASE", .. }')],
            [base[0], base[1], ('src/commands/b.lis', 'let t = s.\n  reveal()')],
            [('src/secret/secret.lis', base[0][1] + '\npub fn peek(\n  s: Secret,\n) -> string {\n  s.value\n}'), base[1]],
            [('src/secret/secret.lis', base[0][1] + '\npub fn chars(s: Secret) -> Slice<rune> { s.value }'), base[1]],
            [('src/secret/secret.lis', base[0][1] + '\npub fn with(s: Secret, f: fn(string)) { f(s.value) }'), base[1]],
            [('src/secret/secret.lis', base[0][1] + '\n  pub fn peek(self) -> Option<string> { Some(self.value) }'), base[1]],
        ]
        for files in more:
            self.assertTrue(violations(files, {}), files)
        twice = [base[0], base[1], ('src/commands/b.lis', 'send(s.reveal())\nsend(s.reveal())')]
        self.assertTrue(violations(twice, {('src/commands/b.lis', 'send(s.reveal())'): 'a send'}))


if __name__ == '__main__':
    unittest.main()
