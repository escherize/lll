"""Every verb takes --json, or says here why it has nothing to print as JSON.

The 1.0 fleet: 'lll finding confirm SLUG --json' was an unknown flag for 3 of
10 workers, who had --json on every other verb they used. The verb list comes
from the binary's completion table, so a new verb fails this test until it
either declares --json or earns an entry below with its reason.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())

DELETE = 'a delete leaves no record to print; the exit code is the result'
ONE_VALUE = 'prints one plain value for a pipe'
WITHOUT_JSON = {
    ('issue', 'download'): 'writes the attachment bytes to stdout',
    ('issue', 'url'): ONE_VALUE,
    ('issue', 'id'): ONE_VALUE,
    ('issue', 'title'): ONE_VALUE,
    ('issue', 'branch-name'): ONE_VALUE,
    ('issue', 'pr'): "drives 'gh pr create'; the gh#N it records shows in 'issue view --json'",
    ('issue', 'delete'): DELETE,
    ('team', 'delete'): DELETE,
    ('member', 'delete'): DELETE,
    ('member', 'remove'): DELETE,
    ('project', 'delete'): DELETE,
    ('label', 'delete'): DELETE,
    ('doc', 'delete'): DELETE,
    ('webhook', 'remove'): DELETE,
    ('bot', '*'): 'prints a one-time credential as a paste-ready prompt; --env is the machine-readable form',
    ('bot', 'create'): 'prints a one-time credential as a paste-ready prompt; --env is the machine-readable form',
    ('bot', 'rotate'): 'prints a one-time credential as a paste-ready prompt; --env is the machine-readable form',
    ('token', 'create'): 'prints the one-time credential as LLL_TOKEN=..., already machine-readable',
    ('member', 'create'): "prints a one-time login handoff; 'lll member list --json' reads the record",
    ('member', 'add'): "prints a one-time login handoff; 'lll member list --json' reads the record",
    ('member', 'invite'): 'prints one-time login handoffs (secrets) once',
    ('member', 'passes'): 'prints one-time login handoffs (secrets) once',
    ('member', 'set-password'): 'a password change has no record to show',
    ('webhook', 'add'): "prints its secret once; 'lll webhook list --json' reads the record",
    ('api', '*'): "a raw passthrough: the body is already the server's JSON",
    ('import', 'github'): "a bulk import prints one line per item; 'lll issue list --json' reads the result",
    ('import', 'dir'): "a bulk import prints one line per item; 'lll issue list --json' reads the result",
    ('attach', '*'): "writes .lll.toml; 'lll config list --json' reads it",
    ('export', '*'): 'writes a directory of Markdown; the files are the result',
    ('skill', 'get'): 'prints the skill itself, as markdown',
    ('up', '*'): 'runs a server',
    ('board', '*'): ONE_VALUE,
    ('login', '*'): "stores a token; 'lll whoami --json' reads the identity",
    ('upgrade', '*'): 'runs or prints an upgrade command',
    ('config', 'check'): 'a health check prints its findings; the exit code is the result',
    ('config', 'get'): ONE_VALUE,
    ('config', 'init'): "writes local configuration; 'lll config list --json' reads it",
    ('config', 'set'): "writes local configuration; 'lll config list --json' reads it",
}


def main():
    with tempfile.TemporaryDirectory(prefix='lll-write-json-') as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_'))}
        env.update(HOME=directory, LLL_URL='http://127.0.0.1:9')
        bash = subprocess.run([binary, 'completions', 'bash'], cwd=directory, env=env, text=True,
                              capture_output=True, timeout=30, check=True).stdout
    rows = dict(re.findall(r"^      ([a-z-]+,[a-z*-]+)\) words='([^']*)' ;;$", bash, re.M))
    # A verb with no flags at all has no flag row; it has no --json either.
    for noun, words in re.findall(r"^      ([a-z-]+)\) words='([^']*)' ;;$", bash, re.M):
        for verb in words.split():
            if not verb.startswith('-') and any(r.startswith(f'{noun},') for r in rows):
                rows.setdefault(f'{noun},{verb}', '')
    assert rows.get('issue,create'), 'no flag rows in the completion script'
    missing, stale = [], []
    for row, words in sorted(rows.items()):
        noun, verb = row.split(',')
        has = '--json' in words.split()
        if (noun, verb) in WITHOUT_JSON:
            if has:
                stale.append(f'lll {noun} {verb} now takes --json; drop its WITHOUT_JSON entry')
        elif not has:
            missing.append(f'lll {noun} {verb}: no --json and no WITHOUT_JSON reason')
    for (noun, verb) in WITHOUT_JSON:
        if f'{noun},{verb}' not in rows:
            stale.append(f'WITHOUT_JSON names lll {noun} {verb}, which has no flag row')
    for line in missing + stale:
        print(line)
    assert not missing and not stale, f'{len(missing)} verbs without --json, {len(stale)} stale entries'
    print(f'--json: {len(rows)} verbs take it or say why not')


main()
