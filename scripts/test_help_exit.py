"""Every noun and verb answers --help with exit 0 and a page on stdout.

The 1.0 fleet: 'lll invite create --help' exited 2 naming its required
--team, so the one command that teaches the verb refused to. The list comes
from the binary's completion table; no server is needed, because help must
never reach one.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
HIDDEN = [('issue', 'read'), ('doc', 'read'), ('finding', 'read'), ('finding', 'view')]


def flags_block(page):
    """The Flags: section of a help page, or '' when it has none."""
    if '\nFlags:\n' not in '\n' + page:
        return ''
    return page.split('Flags:\n', 1)[1]


def main():
    with tempfile.TemporaryDirectory(prefix='lll-help-exit-') as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_'))}
        env.update(HOME=directory, LLL_URL='http://127.0.0.1:9')

        def run(*args):
            return subprocess.run([binary, *args], cwd=directory, env=env, text=True,
                                  capture_output=True, timeout=30, stdin=subprocess.DEVNULL)

        bash = run('completions', 'bash').stdout
        verb_rows = dict(re.findall(r"^      ([a-z-]+)\) words='([^']*)' ;;$", bash, re.M))
        nouns = [n for n in re.search(r"words='(issue [^']*)'", bash).group(1).split() if not n.startswith('-')]
        assert 'invite' in nouns, nouns
        cases = []
        for noun in nouns:
            cases.append([noun, '--help'])
            verbs = [w for w in verb_rows.get(noun, '').split() if not w.startswith('-')]
            cases += [[noun, verb, '--help'] for verb in verbs]
        cases += [[noun, verb, '--help'] for noun, verb in HIDDEN]
        cases.append(['--help'])
        wrong = []
        for args in cases:
            done = run(*args)
            if done.returncode != 0 or not done.stdout.strip():
                wrong.append(f"lll {' '.join(args)}: exit {done.returncode}: {(done.stderr or done.stdout).strip()[:160]}")
            # No page lists a flag twice (1.0 fleet: 'lll issue --help' had
            # two --reason rows).
            rows = re.findall(r'^  (--?[\w-]+)(?:,| {2}|$)', flags_block(done.stdout), re.M)
            twice = sorted({r for r in rows if rows.count(r) > 1})
            if twice:
                wrong.append(f"lll {' '.join(args)}: flags listed twice: {', '.join(twice)}")
    for line in wrong:
        print(line)
    assert not wrong, f'{len(wrong)} of {len(cases)} help requests did not exit 0 with a page'
    print(f'Help exits: {len(cases)} help requests across {len(nouns)} nouns all exit 0')


main()
