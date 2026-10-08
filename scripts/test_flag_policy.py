"""Help, messages and docs spell every command and flag the canonical way (LLL-644).

D6 gives each short flag one meaning and keeps the old spellings only as
aliases. An alias that leaks back into a help page, an error message or the
README teaches it again, and a flag the parser does not know is a help/parser
mismatch. This test reads the spec from the binary, then checks every
`lll NOUN VERB ...` example it can find:

- in every help page the binary prints;
- in every string literal under src/ (help text and error messages);
- in README.md, docs/ and the skills.

Each flag in an example must be the canonical spelling of a flag that verb
declares, and each verb must be the canonical verb. Help text must not use a
spelling that is only ever an alias, such as '-d' or '--ro'.

The spec comes from the "unknown flag" refusal, which prints the verb's usage
line and its generated Flags: block even for verbs with a hand-written page.
"""
import html
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
ROOT = Path(__file__).resolve().parents[1]
PROBE = '--zz-policy-probe'

# Historical records: they describe what the surface WAS.
SKIP_DOCS = {'CHANGELOG.md', 'surface-inventory.md'}


def run(directory, env, *args):
    done = subprocess.run([binary, *args], cwd=directory, env=env, text=True,
                          capture_output=True, timeout=30)
    return done.stdout + done.stderr


def parse_spec(text):
    """{spelling: (canonical, takes_value)} from a refusal's usage + Flags."""
    usage = ''
    for line in text.splitlines():
        if line.startswith('usage: '):
            usage = line
            break
    valued = set(re.findall(r'\[?(-[-\w]+) [^\s\]]+\]?', usage))
    spec = {}
    in_flags = False
    for line in text.splitlines():
        if line == 'Flags:':
            in_flags = True
            continue
        if not in_flags:
            continue
        match = re.match(r'^  (-[-\w]+(?:, -[-\w]+)*)(?:  |$)', line)
        if not match:
            continue
        names = match.group(1).split(', ')
        for name in names:
            spec[name] = (names[0], names[0] in valued)
    return spec


def discover(directory, env):
    """{noun: {verb or '': spec}}, verb aliases {(noun, alias): canonical}."""
    bash = run(directory, env, 'completions', 'bash')
    verb_rows = dict(re.findall(r"^      ([a-z-]+)\) words='([^']*)' ;;$", bash, re.M))
    flag_rows = dict(re.findall(r"^      ([a-z-]+,[a-z*-]+)\) words='([^']*)' ;;$", bash, re.M))
    nouns = re.search(r"words='(issue [^']*)'", bash).group(1).split()
    table = {}
    verb_alias = {}
    for noun in nouns:
        if noun.startswith('-') or noun == 'help':
            continue
        own = flag_rows.get(f'{noun},*', '').split()
        verbs = [w for w in verb_rows.get(noun, '').split() if w not in own]
        table[noun] = {'': parse_spec(run(directory, env, noun, PROBE))}
        assert table[noun][''] or not own, f"'lll {noun} {PROBE}' prints no Flags: block"
        refusals = {verb: run(directory, env, noun, verb, PROBE) for verb in verbs}
        for verb, refusal in refusals.items():
            table[noun][verb] = parse_spec(refusal)
            completed = flag_rows.get(f'{noun},{verb}', '').split()
            assert table[noun][verb] or not completed, f"'lll {noun} {verb} {PROBE}' prints no Flags: block"
            # A verb alias resolves to the same command; its refusal names
            # the canonical verb in the usage line.
            found = re.search(rf'usage: lll {noun} (\S+)([^\n]*)', refusal)
            if found and found.group(1) != verb and found.group(1) in verbs \
                    and not re.search(rf'lll {noun} {re.escape(verb)}\b', found.group(2)):
                verb_alias[(noun, verb)] = found.group(1)
    return table, verb_alias


def help_pages(directory, env, table):
    pages = {'lll --help': run(directory, env, '--help')}
    for noun, verbs in table.items():
        pages[f'lll {noun} --help'] = run(directory, env, noun, '--help')
        for verb in verbs:
            if verb:
                pages[f'lll {noun} {verb} --help'] = run(directory, env, noun, verb, '--help')
    return pages


def string_literals(source):
    """Contents of the "..." literals in a .lis file, comments skipped."""
    out = []
    i = 0
    n = len(source)
    while i < n:
        if source.startswith('//', i):
            i = source.find('\n', i)
            if i < 0:
                break
            continue
        if source[i] == '"':
            i, text = read_string(source, i + 1)
            out.append(text)
            continue
        i += 1
    return out


def read_string(source, i):
    """Read to the closing quote; f-string braces may nest quotes."""
    text = []
    depth = 0
    while i < len(source):
        ch = source[i]
        if ch == '\\':
            nxt = source[i + 1:i + 2]
            text.append({'n': '\n', 't': '\t', '"': '"', '\\': '\\'}.get(nxt, nxt))
            i += 2
            continue
        if depth == 0 and ch == '"':
            return i + 1, ''.join(text)
        if ch == '{':
            depth += 1
        elif ch == '}' and depth > 0:
            depth -= 1
        elif ch == '"' and depth > 0:
            i, inner = read_string(source, i + 1)
            text.append(inner)
            continue
        text.append(ch)
        i += 1
    return i, ''.join(text)


EXAMPLE = re.compile(r"(?<![\w/.-])lll ([a-z][a-z-]*)(?: (--list|[a-z][a-z-]*))?")
FLAG = re.compile(r'^(--?[A-Za-z][\w-]*)(=.*)?$')
STOP = re.compile(r"\s(?:#|\|\||\||;|&&|>|<|then)\s|\s->\s|\s{3,}|,\s")


def examples(text):
    """(noun, verb, [args]) for each `lll noun verb ...` in text."""
    for match in EXAMPLE.finditer(text):
        start = match.start()
        before = text[start - 1] if start > 0 else ''
        noun, verb = match.group(1), match.group(2) or ''
        end_of_line = text.find('\n', match.end())
        rest = text[match.end():] if end_of_line < 0 else text[match.end():end_of_line]
        if before in "'`":
            end = rest.find(before)
            rest = rest if end < 0 else rest[:end]
        else:
            # Unquoted: a code line or prose. Stop at shell operators, at the
            # wide gap before an aligned comment, and at a closing quote.
            stop = STOP.search(rest)
            rest = rest if stop is None else rest[:stop.start()]
            for quote in "'`":
                cut = rest.find(quote)
                if cut >= 0 and rest.count(quote) % 2 == 1:
                    rest = rest[:cut]
        try:
            args = shlex.split(rest)
        except ValueError:
            args = rest.split()
        yield noun, verb, args


def check_example(table, verb_alias, noun, verb, args):
    """Problems with one example, as strings."""
    if noun not in table:
        return []
    verbs = table[noun]
    tabled = len(verbs) > 1
    problems = []
    if tabled:
        if verb == '':
            return []
        if (noun, verb) in verb_alias:
            problems.append(f"verb alias '{verb}' (canonical '{verb_alias[(noun, verb)]}')")
            verb = verb_alias[(noun, verb)]
        if verb in verbs:
            spec = verbs[verb]
        elif verbs['']:
            # A verb-less form beside a sub-verb: 'lll bot bot-NAME'.
            spec = verbs['']
            args = [verb] + args
        else:
            return problems
    else:
        spec = verbs['']
        args = ([verb] if verb else []) + args
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg == '--':
            break
        match = FLAG.match(arg.rstrip('.,;:)'))
        if not match or arg in ('-h', '--help'):
            continue
        name = match.group(1)
        if name not in spec:
            problems.append(f"'{name}' is not a flag of 'lll {noun} {verb}'".replace('  ', ' ').replace(" '", " '"))
            continue
        canonical, valued = spec[name]
        if canonical != name:
            problems.append(f"alias '{name}' (canonical '{canonical}')")
        skip = valued and match.group(2) is None
    return problems


def main():
    with tempfile.TemporaryDirectory(prefix='lll-flag-policy-') as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith('LLL_') and k not in ('XDG_CONFIG_HOME',)}
        env['HOME'] = directory
        env['LLL_URL'] = 'http://127.0.0.1:9'
        table, verb_alias = discover(directory, env)
        assert table.get('issue', {}).get('create'), 'no spec discovered for issue create'
        assert table['issue']['create'].get('-b'), table['issue']['create']
        pages = help_pages(directory, env, table)

    canonical = {c for verbs in table.values() for spec in verbs.values() for c, _ in spec.values()}
    alias_only = {s for verbs in table.values() for spec in verbs.values()
                  for s, (c, _) in spec.items() if s != c} - canonical

    problems = []
    for where, text in pages.items():
        for noun, verb, args in examples(text):
            for p in check_example(table, verb_alias, noun, verb, args):
                problems.append(f'{where}: lll {noun} {verb}: {p}')
        # Outside the Flags: label column, an alias-only spelling is a leak.
        for line in text.splitlines():
            if re.match(r'^  -', line):
                line = re.sub(r'^  (-[-\w]+(?:, -[-\w]+)*)', '', line)
            for token in re.findall(r"(?<![\w-])(--?[A-Za-z][\w-]*)", line):
                if token in alias_only:
                    problems.append(f"{where}: alias-only spelling '{token}' in: {line.strip()}")

    sources = sorted(p for p in (ROOT / 'src').rglob('*.lis') if not p.name.endswith('.test.lis'))
    docs = [ROOT / 'README.md', *sorted((ROOT / 'docs').glob('*.md')),
            *sorted((ROOT / '.claude' / 'skills').glob('*/SKILL.md'))]
    corpus = [(str(p.relative_to(ROOT)), s) for p in sources for s in string_literals(p.read_text())]
    corpus += [(str(p.relative_to(ROOT)), p.read_text()) for p in docs if p.name not in SKIP_DOCS]
    # The board's copy, the landing page and the server's own messages.
    pages_html = [*sorted((ROOT / 'web' / 'templates').glob('*.html')), ROOT / 'docs' / 'index.html']
    corpus += [(str(p.relative_to(ROOT)), html.unescape(re.sub(r'<[^>]+>', '', p.read_text()))) for p in pages_html]
    corpus += [(str(p.relative_to(ROOT)), p.read_text())
               for p in sorted((ROOT / 'gopb').glob('*.go')) if not p.name.endswith('_test.go')]
    for where, text in corpus:
        for noun, verb, args in examples(text):
            for p in check_example(table, verb_alias, noun, verb, args):
                problems.append(f'{where}: lll {noun} {verb}: {p}')

    unique = sorted(set(problems))
    for line in unique:
        print(line)
    assert not unique, f'{len(unique)} non-canonical or unknown spellings (LLL-644)'
    print(f'Flag policy: {len(table)} nouns, {len(pages)} help pages, {len(corpus)} texts use canonical spellings')


main()
