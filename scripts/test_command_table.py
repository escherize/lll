"""One command table, one parser, one rule for wrong guesses (LLL-684).

Each verb used to parse and validate its own arguments, and each fleet run
patched the symptoms one verb at a time: usage errors that exited 1, --help
that exited 2, `version --zz` that exited 0, hints hand-written in four
files. Now commands.nouns() (src/commands/table.lis) declares every noun and
verb, flags.parse_command_line parses argv against it before any handler
runs, and src/flags/hints.lis is the one rule that answers a wrong guess.

This test reads the non-test .lis sources and holds that shape:

- every handler reads only flags its own spec declares (Parsed also stops
  with an internal error at run time on such a read; this finds it without
  running the verb). For each
  flags.Command literal it follows calls from the `run:` handler and from the
  `spec:` expression through src/commands and src/flags, collects the flag
  names read (`.one("--x")`, `.given(...)`, `.all(...)`, or a helper called
  with the parsed value and a flag literal) and the names declared (`name:`
  in a Flag), and fails on a read the spec never declares. Such a read is
  always empty: it is how a renamed flag kept a dead branch (attach's -k);
- every function that builds a flags.Command is reachable from nouns(), and
  nothing outside src/flags parses argv itself (flags.parse, parse_n,
  help_requested; os.Args outside src/main.lis), so no verb lives outside
  the table;
- no spec declares --help (the table answers it, exit 0, everywhere);
- the wording of a did-you-mean or recovery hint ("did you mean", "unknown
  ... command", "it is ... verb", "(use one of: ...)", "; try '...'", "to X
  one, run", a `Guess` table) appears only in src/flags/hints.lis, so a
  hand-written hint table cannot reappear beside a verb.

Known limits: the call graph is by name within src/commands and src/flags,
so it over-approximates (a helper that reads a flag on one path counts for
every caller) and does not see a flag name built at run time.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FN = re.compile(r'^[ \t]*(?:pub )?fn (\w+)', re.M)
READ = re.compile(r'\.(?:one|given|all)\("(-[-\w]+)"\)|\b\w+\((?:p|parsed|input\.parsed), "(-[-\w]+)"')
DECL = re.compile(r'\bname:\s*"(-[-\w]+)"')
CALL = re.compile(r'(?<![\w.])(\w+)\s*\(')
FLAGS_CALL = re.compile(r'\bflags\.(\w+)\s*\(')

# Hint wording outside the rule, each with why it is not a command-line hint.
HINT = re.compile(r'did you mean|unknown (?:[a-z]+ )*command|it is an? [a-z]+ verb|\bGuess\s*\{'
                  r"|\bno [a-z]+ verb\b|\bto [a-z]+ (?:one|it),? run\b|\(use one of: |\(use: [a-z]|got '[^']*'; try '|; keys: |does not [a-z]+; to ")
HINT_ALLOW = {
    'src/query/query.lis': "the board's state parser for URL filters; the CLI refuses the same value first, in the parser, with the same words (issue_filters.test pins that they match)",
}
# The only places that may read argv or call the parser directly.
PARSER_ALLOW = {
    'src/commands/scope.lis': 'takes --team off the command line before the settings are built (flags.extract_team)',
}


def strip(code):
    """The code without comments and with string bodies emptied."""
    code = re.sub(r'//[^\n]*', '', code)
    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)


def functions(path):
    text = path.read_text()
    found = list(FN.finditer(text))
    out = {}
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        out[m.group(1)] = text[m.start():end]
    return out


def sources(root):
    return [p for p in sorted((root / 'src').rglob('*.lis')) if not p.name.endswith('.test.lis')]


class Graph:
    def __init__(self, root):
        self.commands = {}
        for p in sorted((root / 'src' / 'commands').glob('*.lis')):
            if not p.name.endswith('.test.lis'):
                self.commands.update(functions(p))
        self.flags = {}
        for p in sorted((root / 'src' / 'flags').glob('*.lis')):
            if not p.name.endswith('.test.lis'):
                self.flags.update(functions(p))

    def closure(self, seeds, seed_text=''):
        """Bodies reachable by call from the named functions and the text."""
        seen, todo, bodies = set(), [], [seed_text]
        for name in seeds:
            if name in self.commands:
                todo.append(('c', name))
        for kind, name in self.calls(seed_text, 'c', root=True):
            todo.append((kind, name))
        while todo:
            key = todo.pop()
            if key in seen:
                continue
            seen.add(key)
            kind, name = key
            body = (self.commands if kind == 'c' else self.flags)[name]
            bodies.append(body)
            todo.extend(self.calls(body, kind))
        return bodies

    def calls(self, body, kind, root=False):
        code = strip(body)
        # Another Command's handler is not called by building the Command:
        # only the root's own run expression is followed.
        if not root:
            code = re.sub(r'\brun:[^\n]*', '', code)
        found = []
        local = self.commands if kind == 'c' else self.flags
        for name in CALL.findall(code):
            if name in local:
                found.append((kind, name))
        for name in FLAGS_CALL.findall(code):
            if name in self.flags:
                found.append(('f', name))
        return found


def command_literals(text):
    """The text of every `flags.Command { ... }` literal."""
    out, i = [], 0
    while (j := text.find('flags.Command {', i)) >= 0:
        k, depth = j + len('flags.Command {'), 1
        while depth:
            depth += {'{': 1, '}': -1}.get(text[k], 0)
            k += 1
        out.append(text[j:k])
        i = k
    return out


def field(literal, name):
    """A field's expression in a Command literal, up to the next field."""
    m = re.search(rf'\b{name}:\s*(.*?)(?=,\s*\n\s*\w+:|,\s*\w+:\s|\s*,?\s*\.\.\s*,?\s*\}}$|\s*\}}$)', literal, re.S)
    return m.group(1) if m else ''


def undeclared_reads(root=ROOT):
    graph = Graph(root)
    found = []
    for path in sorted((root / 'src' / 'commands').glob('*.lis')):
        if path.name.endswith('.test.lis'):
            continue
        for literal in command_literals(path.read_text()):
            name = re.search(r'name: "([^"]+)"', literal).group(1)
            run, spec = field(literal, 'run'), field(literal, 'spec')
            seeds = [run.strip()] if re.fullmatch(r'\w+', run.strip()) else []
            reads = set()
            for body in graph.closure(seeds, run):
                # A Command literal met on the way is built, not run.
                reads |= {a or b for a, b in READ.findall(re.sub(r'\brun:[^\n]*', '', body))}
            reads |= {a or b for a, b in READ.findall(run)}
            declared = set()
            for body in graph.closure([], spec):
                declared |= set(DECL.findall(body))
            for flag in sorted(reads - declared):
                found.append(f'{path.relative_to(root).as_posix()}: {name} reads {flag}, which its spec does not declare')
    return found


def unreachable_commands(root=ROOT):
    graph = Graph(root)
    table = (root / 'src' / 'commands' / 'table.lis').read_text()
    nouns = re.search(r'pub fn nouns\(.*?\n}\n', table, re.S).group(0)
    reached = set()
    for body in graph.closure([], nouns):
        m = FN.match(body)
        if m:
            reached.add(m.group(1))
    found = []
    for path in sorted((root / 'src' / 'commands').glob('*.lis')):
        if path.name.endswith('.test.lis'):
            continue
        for fn, body in functions(path).items():
            if 'flags.Command {' in body and fn not in reached:
                found.append(f'{path.relative_to(root).as_posix()}: {fn} builds a flags.Command that commands.nouns() never reaches')
    return found


def own_parsers(root=ROOT):
    found = []
    for path in sources(root):
        rel = path.relative_to(root).as_posix()
        if rel.startswith('src/flags/') or rel in PARSER_ALLOW:
            continue
        code = strip(path.read_text())
        for n, line in enumerate(code.split('\n'), 1):
            if re.search(r'\bflags\.(?:parse|parse_n|help_requested|extract_team)\s*\(', line):
                found.append(f'{rel}:{n}: parses argv outside the table')
            if 'os.Args' in line and rel != 'src/main.lis':
                found.append(f'{rel}:{n}: reads os.Args; only main hands argv to the parser')
    return found


def help_flags(root=ROOT):
    found = []
    for path in sources(root):
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(path.read_text().split('\n'), 1):
            if re.search(r'\bname:\s*"--help"', line):
                found.append(f'{rel}:{n}: declares --help; the table answers it for every verb')
    return found


def stray_hints(root=ROOT):
    found = []
    for path in sources(root):
        rel = path.relative_to(root).as_posix()
        if rel == 'src/flags/hints.lis' or rel in HINT_ALLOW or rel.startswith('src/serve/'):
            continue
        text = re.sub(r'//[^\n]*', '', path.read_text())
        for n, line in enumerate(text.split('\n'), 1):
            if HINT.search(line):
                found.append(f'{rel}:{n}: {line.strip()[:100]}')
    return found


class CommandTableTest(unittest.TestCase):
    def test_handlers_read_only_flags_their_spec_declares(self):
        found = undeclared_reads()
        self.assertEqual(found, [], 'a handler reads a flag its spec does not declare (declare it, or stop reading it):\n' + '\n'.join(found))

    def test_every_command_is_in_the_table(self):
        found = unreachable_commands() + own_parsers()
        self.assertEqual(found, [], 'a verb outside the command table (add it to commands.nouns()):\n' + '\n'.join(found))

    def test_no_spec_declares_help(self):
        found = help_flags()
        self.assertEqual(found, [], 'help is the table\'s, not a flag (give the Command a page instead):\n' + '\n'.join(found))

    def test_hints_live_in_the_one_rule(self):
        found = stray_hints()
        self.assertEqual(found, [], 'a hand-written hint outside src/flags/hints.lis (add a Guess there instead):\n' + '\n'.join(found))

    def test_the_checks_see_what_they_claim(self):
        # Fixtures, so a check that silently matches nothing fails here.
        literal = 'flags.Command {\n  name: "x",\n  spec: [flags.Flag { name: "--a", .. }],\n  run: |i| go(i),\n  ..\n}'
        self.assertEqual(command_literals('a ' + literal + ' b'), [literal])
        self.assertEqual(field(literal, 'run'), '|i| go(i)')
        self.assertEqual({a or b for a, b in READ.findall('p.one("--a") secret.from_stdin(p, "--b")')}, {'--a', '--b'})
        self.assertTrue(HINT.search('f"unknown issue command: \'{w}\'"'))
        self.assertTrue(HINT.search('"it is a member verb"'))
        for planted in ["no issue verb 'rm'; to remove one run lll issue delete", "unknown kind 'x' (use one of: a, b)",
                        "bad name - got 'x'; try 'lll bot create bot-x'", "unknown key 'x'; keys: a, b",
                        "update does not claim; to claim, run: lll issue claim KEY"]:
            self.assertTrue(HINT.search(planted), planted)
        for allowed in list(HINT_ALLOW) + list(PARSER_ALLOW):
            self.assertTrue((ROOT / allowed).exists(), allowed)


if __name__ == '__main__':
    unittest.main()
