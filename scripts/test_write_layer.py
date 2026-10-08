"""Every write to a lll record goes through src/writes/ (LLL-659).

The CLI and the board used to write the same records separately: the CLI
joined JSON strings, the board marshalled its own structs, and the two
drifted (the cross-team reference bug). The write layer is the one place a
create, update or delete is spelled. This test keeps it that way: outside
src/writes/ and the HTTP client itself (src/pb/), no source makes a mutating
request through the client:

- `.post(`, `.patch(`, `.post_as(`, `.patch_as(`, `.delete_as(`,
  `.post_idempotent(`, `.patch_with_stamp(`, `.patch_with_stamp_as(`,
  `.post_anon(`, `post_anon_to(`, whatever the receiver is called;
- `.send_as(` at all: it is the layer's own primitive;
- `.delete(` whose first argument names an API path or a path variable
  (Map.delete takes a key).

Calls are matched across line breaks, as the formatter splits them. A call
that creates no record is allowed when one of its string arguments is
exactly one of the NOT_RECORD_WRITES paths (anchored, so a record path that
merely contains one is not), or when its path is the named variable in
ALLOW_VARIABLES. `//` comments are skipped. Tests are skipped: they may fake
a client.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

CALL = re.compile(
    r'\.(post|patch|post_as|patch_as|delete_as|post_idempotent|patch_with_stamp|patch_with_stamp_as|post_anon|send_as|delete)\s*\('
    r'|\b(post_anon_to)\s*\(',
)

# A whole path argument, and why that request is not a record write.
NOT_RECORD_WRITES = {
    r'/api/collections/(members|_superusers)/auth-with-password': 'a login: exchanges a password for a token',
    r'/api/collections/members/impersonate/\{[^}]*\}': 'mints a token for an existing member',
    r'/api/lll/bots/rotate': 'mints a new token for an existing bot',
    r'/api/lll/invites(/redeem)?': 'mints or redeems an invite code (gopb owns the record)',
    r'/api/files/token': 'a short-lived file-read token',
    r'/api/realtime': 'a realtime subscription',
}
# (path, variable) -> reason, for a path held in a variable.
ALLOW_VARIABLES = {
    ('src/commands/login.lis', 'auth_path'): 'the member or superuser auth-with-password path',
}

LAYER = ('src/writes/', 'src/pb/')


def strip_comments(source):
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


def call_args(text, open_paren):
    """The top-level arguments of the call whose '(' is at open_paren."""
    depth, i, start, args, in_str = 0, open_paren, open_paren + 1, [], False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
            if depth == 0:
                args.append(text[start:i].strip())
                return args
        elif c == ',' and depth == 1:
            args.append(text[start:i].strip())
            start = i + 1
        i += 1
    return args


def literal(arg):
    m = re.fullmatch(r'f?"((?:[^"\\]|\\.)*)"', arg)
    return m.group(1) if m else None


def path_arg(name, args):
    """The argument a request goes to: the second for post_anon_to (after
    the base url), else the first."""
    index = 1 if name == 'post_anon_to' else 0
    return args[index] if len(args) > index else ''


def allowed(rel, name, args):
    if name == 'send_as':
        return False
    path = path_arg(name, args)
    text = literal(path)
    if text is not None and any(re.fullmatch(p, text) for p in NOT_RECORD_WRITES):
        return True
    return (rel, path) in ALLOW_VARIABLES


def is_request_delete(args):
    first = args[0] if args else ''
    return '/api' in first or re.search(r'path|url', first, re.I) is not None


def violations_in(rel, source):
    text = strip_comments(source)
    found = []
    for m in CALL.finditer(text):
        name = m.group(1) or m.group(2)
        args = call_args(text, m.end() - 1)
        if name == 'delete' and not is_request_delete(args):
            continue
        if allowed(rel, name, args):
            continue
        line = text.count('\n', 0, m.start()) + 1
        found.append(f'{rel}:{line}: .{name}({", ".join(args)[:80]})')
    return found


def violations(root=ROOT):
    found = []
    for path in sorted((root / 'src').rglob('*.lis')):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(LAYER) or rel.endswith('.test.lis'):
            continue
        found += violations_in(rel, path.read_text())
    return found


class WriteLayerTest(unittest.TestCase):
    def test_no_record_write_outside_the_write_layer(self):
        found = violations()
        self.assertEqual(found, [], 'record writes outside src/writes/ (add a function there and call it):\n' + '\n'.join(found))

    def test_the_check_sees_a_planted_write(self):
        # Each spelling the check claims to catch, in the formatter's shapes.
        planted = [
            'let _ = ctx.post("/api/collections/issues/records", body)?',
            'let _ = ctx.patch(f"/api/collections/issues/records/{id}", body)?',
            'let _ = ctx.send_as(\n    caller,\n    "DELETE",\n    path,\n    "",\n    "application/json",\n  )?',
            'let _ = ctx.send_as(caller, method, path, "", "application/json")?',
            'let _ = ctx.delete(path)?',
            'let _ = board.delete(f"/api/collections/labels/records/{id}")?',
            'let _ = ctx.patch_as(path, body, su)?',
            'let _ = ctx.post_anon("/api/collections/issues/records", body)?',
            'let _ = pb.post_anon_to(base, "/api/collections/issues/records", body)?',
            'let _ = ctx.post("/api/collections/issues/records?x=/api/realtime", body)?',
            'let _ = ctx.post(\n    "/api/collections/issues/records",\n    body,\n  )?',
            'let _ = ctx.post_as("/api/collections/issues/records", "{}", "/api/realtime")?',
        ]
        for source in planted:
            self.assertTrue(violations_in('src/commands/x.lis', source), source)
        clean = [
            'self.jobs.delete(key)',
            'last.delete(rec.id)',
            'ctx.get(path)',
            '// ctx.post("/x", y)',
            'ctx.post_anon(\n    "/api/collections/_superusers/auth-with-password",\n    payload,\n  )',
            'ctx.post_as(f"/api/collections/members/impersonate/{member.id}", p, su)',
            'ctx.post("/api/files/token", "{}")',
        ]
        for source in clean:
            self.assertFalse(violations_in('src/commands/x.lis', source), source)


if __name__ == '__main__':
    unittest.main()
