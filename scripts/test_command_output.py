"""Commands return their output; one renderer writes it (LLL-683).

A command builds an output.Output (data for stdout, notices for stderr) and
returns it; main's render is the one place that writes a command's outcome,
and it decides the streams: data to stdout, notices to stderr, and under
--json or --env the data alone. Commands that printed for themselves drifted
one by one (the 1.0 fleet: notices on stdout, --env on stderr, "Error:" for
nothing to do), and each fix was a patch on one verb.

This test keeps it that way. In src/commands and src/main.lis it finds every
fmt.Print*, fmt.Fprint*, os.Stdout and os.Stderr outside `//` comments, and
fails on any not inside a function ALLOW names. ALLOW is {(path, fn): reason}
for output that cannot wait for a return value: a stream that runs until
interrupted, an interactive prompt that needs its answer first, a child
process whose output passes straight through, and the renderer itself. An
entry that no longer writes fails too, so the list only shrinks.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

WRITES = re.compile(r'\bfmt\.(?:Print|Println|Printf|Fprint|Fprintln|Fprintf)\s*\(|\bos\.(?:Stdout|Stderr)\b')
FN = re.compile(r'^(?:pub )?fn (\w+)', re.M)

ALLOW: dict[tuple[str, str], str] = {
    ('src/main.lis', 'render'): 'the renderer: the one place a command outcome is written',
    ('src/main.lis', 'write'): 'the renderer: writes an Output\'s parts to their streams',
    ('src/commands/watch.lis', 'watch_stream'): 'lll watch: an event stream that runs until interrupted',
    ('src/commands/watch.lis', 'run_issue_watch'): 'lll issue watch: an event stream that runs until interrupted or --until',
    ('src/commands/watch.lis', 'watch_ready'): 'lll watch --ready: an event stream that runs until interrupted',
    ('src/commands/up.lis', 'up'): 'lll up: the boot banner is on screen while the server it starts keeps running',
    ('src/commands/up_team.lis', 'ensure_team'): 'lll up: boot banner line',
    ('src/commands/up_team.lis', 'resolve_team'): 'lll up: boot banner line',
    ('src/commands/up_team.lis', 'board_identity'): 'lll up: boot banner lines',
    ('src/commands/up_team.lis', 'ask_team'): 'lll up: interactive team key prompt',
    ('src/commands/up_team.lis', 'save_team'): 'lll up: boot banner line',
    ('src/commands/demo.lis', 'seed_demo'): 'lll up --demo: boot banner lines',
    ('src/commands/demo.lis', 'point_cli_at_demo'): 'lll up --demo: boot banner lines',
    ('src/commands/delete.lis', 'confirmed'): 'interactive [y/N] prompt before a delete',
    ('src/commands/login.lis', 'ask_email'): 'interactive email prompt',
    ('src/commands/issue_write.lis', 'pr_cmd'): 'lll issue pr: gh pr create output passes straight through',
    ('src/commands/import.lis', 'gh_issue_list'): 'lll import github: gh issue list stderr passes straight through',
    ('src/commands/import.lis', 'progress'): 'lll import github: one line per created issue as it lands, so a long import shows progress',
    ('src/commands/upgrade.lis', 'run_upgrade'): 'lll upgrade: notes before Homebrew runs, then its output passes through',
}


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


def writes(rel, source):
    """[(rel, line, fn, call)] for every direct write in `source`; `fn` is the
    top-level function it sits in ("" for none)."""
    code = strip_comments(source)
    starts = [(m.start(), m.group(1)) for m in FN.finditer(code)]
    found = []
    for m in WRITES.finditer(code):
        fn = ''
        for at, name in starts:
            if at > m.start():
                break
            fn = name
        found.append((rel, code.count('\n', 0, m.start()) + 1, fn, m.group(0).rstrip('( ')))
    return found


def sources():
    yield ROOT / 'src' / 'main.lis'
    for path in sorted((ROOT / 'src' / 'commands').glob('*.lis')):
        if not path.name.endswith('.test.lis'):
            yield path


def all_writes():
    found = []
    for path in sources():
        found += writes(path.relative_to(ROOT).as_posix(), path.read_text(encoding='utf-8'))
    return found


class CommandOutputTest(unittest.TestCase):
    def test_commands_return_output_instead_of_printing(self):
        stray = [w for w in all_writes() if (w[0], w[2]) not in ALLOW]
        self.assertEqual(
            stray, [],
            'a command writes stdout/stderr itself (LLL-683); return an output.Output '
            '(output.line, .notice, json_value, ...) and let main render it, or add an '
            'ALLOW entry that says why it cannot wait:\n'
            + '\n'.join(f'  {rel}:{line}: {call} in fn {fn}' for rel, line, fn, call in stray),
        )

    def test_every_allowed_function_still_writes(self):
        writers = {(rel, fn) for rel, _, fn, _ in all_writes()}
        stale = sorted(set(ALLOW) - writers)
        self.assertEqual(stale, [], 'ALLOW entries that no longer write; remove them: ' + repr(stale))

    def test_the_scanner_catches_what_it_hunts(self):
        planted = '''fn a() {
  fmt.Println("x")
  // fmt.Println("prose, not a call")
  let _ = fmt.Fprintln(os.Stderr, "y")
}
pub fn b() -> int {
  foo("http://h", os.Stdout)
}
'''
        self.assertEqual(
            [(line, fn, call) for _, line, fn, call in writes('src/commands/x.lis', planted)],
            [(2, 'a', 'fmt.Println'), (4, 'a', 'fmt.Fprintln'), (4, 'a', 'os.Stderr'), (7, 'b', 'os.Stdout')],
        )


if __name__ == '__main__':
    unittest.main()
