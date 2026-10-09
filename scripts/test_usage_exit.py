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
HIDDEN = [('issue', 'read'), ('doc', 'read'), ('finding', 'read'), ('finding', 'view'), ('config', 'show')]
# First words that print the top-level usage whatever follows.
USAGE_PAGES = {'--help', '-h'}


def dispatched_nouns():
    """Every noun and noun spelling in the command table (LLL-684,
    src/commands/table.lis), which also holds the nouns completion does not
    list (version's --version and -v)."""
    source = (Path(__file__).resolve().parent.parent / 'src' / 'commands' / 'table.lis').read_text()
    body = re.search(r'pub fn nouns\(.*?\n}\n', source, re.S).group(0)
    names = re.findall(r'flags\.Noun \{ name: "([^"]+)"(?:, alias: "([^"]*)")?', body)
    return [w for name, alias in names for w in [name, *alias.split()]]


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
        dispatched = dispatched_nouns()
        assert {'version', '--version', '-v'} <= set(dispatched), dispatched
        missing = sorted(set(nouns) - set(dispatched))
        assert not missing, f'completed but not dispatched: {missing}'
        nouns += [n for n in dispatched if n not in nouns and n not in USAGE_PAGES]
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
        # PR #348 review: the wording these command lines get, through the real
        # binary. (args, exit code, must contain, must not contain).
        worded = [
            (['issue', 'comment', 'ENG-1', '1', '--delete'], 2, "unknown flag: '--delete'", 'run: lll issue delete'),
            (['issue', 'comment', 'ENG-1', '--edit'], 2, "unknown flag: '--edit'", 'run: lll issue'),
            (['label', 'edit', 'bug', '--delete'], 2, "unknown flag: '--delete'", 'run: lll'),
            (['issue', 'list', '--url', 'http://x'], 2, 'This command takes no --url', 'does not url'),
            (['issue', 'update', 'ENG-1', '--claim'], 2, 'to claim, run: lll issue claim ENG-1', None),
            (['whoami', '--team', 'X'], 2, 'run it bare to see the identity', None),
            (['version', '--team', 'X'], 2, 'server-wide: no team applies', 'LLL_TEAM='),
            (['completions', 'bash', '--url', 'http://x'], 2, "unknown flag: '--url'", 'endpoint'),
            (['team', 'set-emoji', 'ENG'], 2, "an empty '' clears it", None),
            (['team', 'set-accent', 'ENG'], 2, "an empty '' clears it", None),
            (['attach', '--key', 'bad!'], 2, 'a team key is a letter', None),
            (['issue', 'create', '-t', 'x', '--priority', '9'], 2, "unknown priority '9'", None),
        ]
        for args, code, want, unwanted in worded:
            done = run(*args)
            said = done.stderr + done.stdout
            if done.returncode != code or want not in said or (unwanted and unwanted in said):
                wrong.append(f"lll {' '.join(args)}: exit {done.returncode}: {said.strip()[:200]}")
        # --help is help, not the version (#340 review).
        for noun in ('version', '--version', '-v'):
            done = run(noun, '--help')
            if done.returncode != 0 or 'Usage' not in done.stdout:
                wrong.append(f"lll {noun} --help: exit {done.returncode}: {done.stdout.strip()[:160]}")
    for line in wrong:
        print(line)
    assert not wrong, f'{len(wrong)} of {len(cases)} bad command lines did not exit 2'
    print(f'Usage exits: {len(cases)} bad command lines across {len(nouns)} nouns all exit 2')


main()
