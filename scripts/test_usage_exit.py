"""Every bad command line exits 2 (docs/cli-contract.md, the 1.0 fleet).

`lll whoami --team FLEET` exited 1 while every table-driven verb exited 2 for
the same mistake, so a script could not tell a typo from a failure. This
drives every noun, every verb and every hidden verb alias with an unknown
flag, and every noun with an unknown verb, and asserts exit 2 for each. The
list comes from the binary's own completion table, so a new noun or verb is
covered with no edit here. No server is needed: a usage error must be decided
before lll talks to one, so LLL_URL points at a closed port.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
PROBE = '--zz-usage-probe'
# Spellings that dispatch but are never completed (flags.Command.hidden_alias
# and hidden verbs); they must refuse a bad flag the same way.
HIDDEN = [('issue', 'read'), ('doc', 'read'), ('finding', 'read'), ('finding', 'view')]


def main():
    with tempfile.TemporaryDirectory(prefix='lll-usage-exit-') as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_'))}
        env.update(HOME=directory, LLL_URL='http://127.0.0.1:9')

        def run(*args):
            return subprocess.run([binary, *args], cwd=directory, env=env, text=True,
                                  capture_output=True, timeout=30, stdin=subprocess.DEVNULL)

        bash = run('completions', 'bash').stdout
        verb_rows = dict(re.findall(r"^      ([a-z-]+)\) words='([^']*)' ;;$", bash, re.M))
        nouns = [n for n in re.search(r"words='(issue [^']*)'", bash).group(1).split() if not n.startswith('-')]
        assert 'whoami' in nouns and 'issue' in nouns, nouns
        cases = []
        for noun in nouns:
            cases.append([noun, PROBE])
            verbs = [w for w in verb_rows.get(noun, '').split() if not w.startswith('-')]
            if verbs:
                cases.append([noun, 'zz-no-such-verb'])
            cases += [[noun, verb, PROBE] for verb in verbs]
        cases += [[noun, verb, PROBE] for noun, verb in HIDDEN]
        wrong = []
        for args in cases:
            done = run(*args)
            if done.returncode != 2:
                wrong.append(f"lll {' '.join(args)}: exit {done.returncode}: {(done.stderr or done.stdout).strip()[:160]}")
    for line in wrong:
        print(line)
    assert not wrong, f'{len(wrong)} of {len(cases)} bad command lines did not exit 2'
    print(f'Usage exits: {len(cases)} bad command lines across {len(nouns)} nouns all exit 2')


main()
