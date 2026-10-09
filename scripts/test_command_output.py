"""Commands return their output; one renderer writes it (LLL-683).

A command builds an output.Output (data for stdout, notices for stderr) and
returns it; main's render is the one place that writes a command's outcome,
and it decides the streams: data to stdout, notices to stderr, and under
--json or --env the data alone. Commands that printed for themselves drifted
one by one (the 1.0 fleet: notices on stdout, --env on stderr, "Error:" for
nothing to do), and each fix was a patch on one verb.

This test keeps it that way. In every non-test .lis file under src/ it finds
every fmt.Print*, fmt.Fprint*, log.Print*/Fatal*/Panic*, os.NewFile,
syscall.Write/Syscall, os.Stdout and os.Stderr outside comments and string
literals, and fails on any not inside a function ALLOW names. CALLERS then
says who may call each allowed writer, so a verb cannot borrow one. A helper in another module that prints is the same
bypass as a verb that prints, so the scan is not limited to src/commands.
ALLOW is {(path, fn): reason} for output that cannot wait for a return value:
a stream that runs until interrupted, progress of a long run, an interactive
prompt that needs its answer first, a child process whose output passes
straight through, and the renderer itself. An entry that no longer writes
fails too, so the list only shrinks.

SERVER is the board: src/serve is the HTTP server 'lll up' runs, and its
lines are the server's log, not a command's output.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

WRITES = re.compile(
    r'\bfmt\.(?:Print|Println|Printf|Fprint|Fprintln|Fprintf)\s*\('
    r'|\blog\.(?:Print|Fatal|Panic)\w*\s*\('
    r'|\bos\.NewFile\s*\('
    r'|\bsyscall\.(?:Write|Syscall\w*|RawSyscall\w*)\s*\('
    r'|\bos\.(?:Stdout|Stderr)\b'
)

SERVER = {'src/serve': 'the board server: its lines are the server log of a running lll up'}
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
    ('src/secret/secret.lis', 'prompted'): 'interactive password prompt, written before the answer is read',
    ('src/secret/secret.lis', 'hidden_line'): 'interactive password prompt without echo',
    ('src/realtime/realtime.lis', 'reconnect'): 'reconnect notices on stderr while a watch stream or the board runs',
    ('src/commands/upgrade.lis', 'run_upgrade'): 'lll upgrade: notes before Homebrew runs, then its output passes through',
}


# Who may call each ALLOW function: all of src/commands is one package, so
# without this any verb could call import's progress() or the delete prompt
# and write into its own --json. Keyed like ALLOW; values are the functions
# (path, fn) that may name it, by call or as a value.
CALLERS: dict[tuple[str, str], set[tuple[str, str]]] = {
    ('src/main.lis', 'render'): {('src/main.lis', 'main')},
    ('src/main.lis', 'write'): {('src/main.lis', 'render')},
    ('src/commands/watch.lis', 'watch_stream'): {('src/commands/watch.lis', 'watch')},
    ('src/commands/watch.lis', 'run_issue_watch'): {('src/commands/watch.lis', 'issue_watch')},
    ('src/commands/watch.lis', 'watch_ready'): {('src/commands/watch.lis', 'watch_stream')},
    ('src/commands/up.lis', 'up'): {('src/main.lis', 'dispatch')},
    ('src/commands/up_team.lis', 'ensure_team'): {('src/commands/up.lis', 'up')},
    ('src/commands/up_team.lis', 'resolve_team'): {('src/commands/up_team.lis', 'ensure_team')},
    ('src/commands/up_team.lis', 'board_identity'): {('src/commands/up.lis', 'up')},
    ('src/commands/up_team.lis', 'ask_team'): {('src/commands/up_team.lis', 'ensure_team')},
    ('src/commands/up_team.lis', 'save_team'): {('src/commands/up_team.lis', 'ensure_team')},
    ('src/commands/demo.lis', 'seed_demo'): {('src/commands/up.lis', 'up')},
    ('src/commands/demo.lis', 'point_cli_at_demo'): {('src/commands/demo.lis', 'seed_demo')},
    ('src/commands/delete.lis', 'confirmed'): {
        ('src/commands/delete.lis', 'confirmed_on_terminal'),
        ('src/commands/doc.lis', 'doc_delete'),
        ('src/commands/issue_write.lis', 'delete_issue'),
    },
    ('src/commands/login.lis', 'ask_email'): {('src/commands/login.lis', 'login')},
    ('src/commands/issue_write.lis', 'pr_cmd'): {('src/commands/issue.lis', 'issue_commands')},
    ('src/commands/import.lis', 'gh_issue_list'): {('src/commands/import.lis', 'import_github')},
    ('src/commands/import.lis', 'progress'): {('src/commands/import.lis', 'import_github')},
    ('src/secret/secret.lis', 'prompted'): {('src/secret/secret.lis', 'read_from'), ('src/secret/secret.lis', 'confirm_from')},
    ('src/secret/secret.lis', 'hidden_line'): {('src/secret/secret.lis', 'prompted')},
    ('src/realtime/realtime.lis', 'reconnect'): {('src/realtime/realtime.lis', 'start')},
    ('src/commands/upgrade.lis', 'run_upgrade'): {('src/commands/upgrade.lis', 'upgrade')},
}


def module_of(rel):
    parts = rel.split('/')
    return parts[1] if len(parts) > 2 else 'main'


def enclosing(code, pos):
    fn = ''
    for m in FN.finditer(code):
        if m.start() > pos:
            break
        fn = m.group(1)
    return fn


def foreign_calls(files):
    """[(rel, line, caller, writer)] for every place `files` ({rel: source},
    tests excluded) names an ALLOW function from outside its CALLERS: by its
    bare name in its own module, as module.fn elsewhere."""
    found = []
    for rel, source in files.items():
        code = code_only(source)
        for (path, fn), callers in CALLERS.items():
            mod = module_of(path)
            pattern = r'(?<![\w.])' + fn + r'\b' if module_of(rel) == mod else r'\b' + mod + r'\.' + fn + r'\b'
            for m in re.finditer(pattern, code):
                if code[max(0, m.start() - 3):m.start()] == 'fn ':
                    continue
                caller = (rel, enclosing(code, m.start()))
                if caller not in callers:
                    found.append((rel, code.count('\n', 0, m.start()) + 1, caller[1], fn))
    return found


def code_only(source):
    """Source with `//` comments and string literal contents blanked, line
    numbers kept. Strings may span lines; r"..." takes no escapes."""
    out, i, n = [], 0, len(source)
    while i < n:
        c = source[i]
        if source.startswith('//', i):
            j = source.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif c == '"':
            raw = i > 0 and source[i - 1] == 'r' and (i < 2 or not (source[i - 2].isalnum() or source[i - 2] == '_'))
            j = i + 1
            while j < n and source[j] != '"':
                j += 2 if source[j] == '\\' and not raw else 1
            out.append('"' + ''.join('\n' if ch == '\n' else ' ' for ch in source[i + 1:j]) + '"')
            i = j + 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def writes(rel, source):
    """[(rel, line, fn, call)] for every direct write in `source`; `fn` is the
    top-level function it sits in ("" for none)."""
    code = code_only(source)
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
    for path in sorted((ROOT / 'src').rglob('*.lis')):
        rel = path.relative_to(ROOT).as_posix()
        if path.name.endswith('.test.lis') or any(rel.startswith(d + '/') for d in SERVER):
            continue
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

    def test_allowed_writers_are_called_only_by_their_callers(self):
        files = {}
        for path in sorted((ROOT / 'src').rglob('*.lis')):
            if not path.name.endswith('.test.lis'):
                files[path.relative_to(ROOT).as_posix()] = path.read_text(encoding='utf-8')
        found = foreign_calls(files)
        self.assertEqual(
            found, [],
            'an allowed writer is called from somewhere CALLERS does not list; a verb that '
            'calls it writes past the renderer:\n'
            + '\n'.join(f'  {rel}:{line}: {fn} calls {w}' for rel, line, fn, w in found),
        )
        self.assertEqual(set(CALLERS), set(ALLOW), 'CALLERS and ALLOW must name the same functions')

    def test_the_caller_check_catches_a_borrowed_writer(self):
        # A review bypass (LLL-683): whoami calling import's progress line.
        planted = {'src/commands/whoami.lis': 'pub fn whoami() {\n  progress("x")\n}\n'}
        self.assertEqual(foreign_calls(planted), [('src/commands/whoami.lis', 2, 'whoami', 'progress')])
        # From another module it is reached as realtime.reconnect.
        planted = {'src/display/display.lis': 'fn x() {\n  realtime.reconnect(a)\n}\n'}
        self.assertEqual(foreign_calls(planted), [('src/display/display.lis', 2, 'x', 'reconnect')])
        # A name in a string or comment is not a call; the listed caller may call.
        self.assertEqual(foreign_calls({'src/commands/x.lis': 'fn a() {\n  out("progress(") // progress(\n}\n'}), [])
        self.assertEqual(foreign_calls({'src/commands/import.lis': 'fn import_github() {\n  progress("x")\n}\n'}), [])

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
        # The bypasses a review found (LLL-683): the log package, a file
        # opened on fd 1, and a printing helper outside src/commands.
        self.assertEqual([c for *_, c in writes('src/commands/x.lis', 'fn a() {\n  log.Println("x")\n}\n')], ['log.Println'])
        self.assertEqual([c for *_, c in writes('src/commands/x.lis', 'fn a() {\n  log.Fatalf("%s", x)\n}\n')], ['log.Fatalf'])
        self.assertEqual([c for *_, c in writes('src/commands/x.lis', 'fn a() {\n  os.NewFile(1, "out").WriteString("x")\n}\n')], ['os.NewFile'])
        self.assertEqual([c for *_, c in writes('src/commands/x.lis', 'fn a() {\n  syscall.Write(1, b)\n}\n')], ['syscall.Write'])
        self.assertEqual([c for *_, c in writes('src/commands/x.lis', 'fn a() {\n  "fmt.Println(" + "x"\n}\n')], [])
        self.assertIn(ROOT / 'src' / 'display' / 'display.lis', list(sources()))
        self.assertNotIn(ROOT / 'src' / 'serve' / 'serve.lis', list(sources()))


if __name__ == '__main__':
    unittest.main()
