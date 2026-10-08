"""Help pages and user-facing messages carry no internal ticket keys.

A key such as LLL-395 or TASK-87 means something only on the board this
project is tracked on; to anyone else running the binary it is noise. Help
and messages say what a thing does, and the CHANGELOG is where ticket keys
belong.

Checked: every help page the binary prints (the top level, each noun and
each verb, enumerated from the bash completion table), and every string
literal under src/ outside unit tests, which is where help text and error
messages are written. Code comments are not checked.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
ROOT = Path(__file__).resolve().parents[1]
KEY = re.compile(r'\b(?:LLL|TASK)-[0-9]+\b')


def string_literals(text):
    """The "..." literals of a .lis file, // comments skipped. Coarse: an
    f-string's nested quotes split it, which only makes more, smaller texts."""
    literals = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith('//', i):
            i = text.find('\n', i)
            if i < 0:
                break
            continue
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == '\\' else 1
            literals.append(text[i + 1:j])
            i = j + 1
            continue
        i += 1
    return literals


def main():
    problems = []
    with tempfile.TemporaryDirectory(prefix='lll-ticket-keys-') as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith('LLL_') and k != 'XDG_CONFIG_HOME'}
        env['HOME'] = directory
        env['LLL_URL'] = 'http://127.0.0.1:9'

        def run(*args):
            done = subprocess.run([binary, *args], cwd=directory, env=env, text=True,
                                  capture_output=True, timeout=30)
            return done.stdout + done.stderr

        bash = run('completions', 'bash')
        verb_rows = dict(re.findall(r"^      ([a-z-]+)\) words='([^']*)' ;;$", bash, re.M))
        nouns = [w for w in re.search(r"words='(issue [^']*)'", bash).group(1).split()
                 if not w.startswith('-') and w != 'help']
        pages = {'lll --help': run('--help')}
        for noun in nouns:
            pages[f'lll {noun} --help'] = run(noun, '--help')
            for verb in verb_rows.get(noun, '').split():
                if not verb.startswith('-'):
                    pages[f'lll {noun} {verb} --help'] = run(noun, verb, '--help')
    assert len(pages) > 50, f'only {len(pages)} help pages found; did the completion table change shape?'
    for where, text in pages.items():
        for key in KEY.findall(text):
            problems.append(f'{where}: {key}')

    sources = sorted(p for p in (ROOT / 'src').rglob('*.lis') if not p.name.endswith('.test.lis'))
    for path in sources:
        for literal in string_literals(path.read_text()):
            for key in KEY.findall(literal):
                problems.append(f'{path.relative_to(ROOT)}: {key} in "{literal[:60]}"')

    for line in sorted(set(problems)):
        print(line)
    assert not problems, f'{len(set(problems))} internal ticket keys in help or messages'
    print(f'Ticket keys: {len(pages)} help pages and {len(sources)} sources carry none')


main()
