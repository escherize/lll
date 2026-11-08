"""Exercise generated completions without configuration or a running board."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
env = {key: value for key, value in os.environ.items() if not key.startswith('LLL_')}
probe = '''source "$1"
shift
COMP_WORDS=("$@")
COMP_CWORD=$((${#COMP_WORDS[@]} - 1))
_lll
printf '%s\\n' "${COMPREPLY[@]}"
'''
with tempfile.TemporaryDirectory(prefix='lll-completion-commands-') as directory:
    scripts = {}
    for shell in ['bash', 'zsh', 'fish']:
        output = subprocess.check_output([binary, 'completions', shell], cwd=directory, env=env, text=True)
        scripts[shell] = output
        assert re.search(r'\bsearch\b', output), shell
        assert re.search(r'\bbot\b', output), shell
        assert 'rotate' in output, shell
        assert ('--refresh' if shell != 'fish' else '-l refresh') in output, shell
        assert ('--duration' if shell != 'fish' else '-l duration') in output, shell
        assert ('--json-errors' if shell != 'fish' else '-l json-errors') in output, shell
    path = Path(directory, 'completion.bash')
    path.write_text(scripts['bash'])
    cases = [
        (['lll', 's'], ['search']),
        (['lll', 'b'], ['bot', 'board']),
        (['lll', 'search', '--'], ['--team', '--refresh', '--json']),
        (['lll', 'search', 'needle', '--'], ['--docs', '--issues']),
        (['lll', 'bot', 'r'], ['rotate']),
        (['lll', 'bot', '--'], ['--duration', '--url']),
        (['lll', 'bot', 'bot-probe', '--'], ['--duration']),
        (['lll', 'bot', 'rotate', 'bot-probe', '--'], ['--duration']),
        (['lll', 'issue', 'c'], ['create', 'close', 'claim', 'comment']),
        (['lll', '--json-e'], ['--json-errors']),
        (['lll', '--json-errors', 's'], ['search']),
        (['lll', '--json-errors', 'issue', 'c'], ['create', 'close', 'claim', 'comment']),
        (['lll', '--json-errors', 'issue', 'list', '--'], ['--json', '--team']),
    ]
    for words, expected in cases:
        completed = subprocess.check_output(['bash', '--noprofile', '--norc', '-c', probe,
                                            'completion-probe', str(path), *words],
                                           cwd=directory, env=env, text=True).splitlines()
        assert all(value in completed for value in expected), (words, completed)
    if shutil.which('zsh'):
        path = Path(directory, 'completion.zsh')
        path.write_text(scripts['zsh'])
        probe = '''compdef() { :; }
compadd() { shift; print -rl -- "$@"; }
source "$1"
shift
words=("$@")
CURRENT=${#words}
_lll
'''
        for words, expected in cases:
            completed = subprocess.check_output(['zsh', '-f', '-c', probe,
                'completion-probe', str(path), *words], cwd=directory, env=env, text=True).splitlines()
            assert all(value in completed for value in expected), (words, completed)
    else:
        print('Native zsh completion probes skipped: zsh is not installed')
    if shutil.which('fish'):
        path = Path(directory, 'completion.fish')
        path.write_text(scripts['fish'])
        for words, expected in cases:
            completed = subprocess.check_output(['fish', '-c',
                'source $argv[1]; complete -C $argv[2]', str(path), ' '.join(words)],
                cwd=directory, env=env, text=True).splitlines()
            completed = [line.split('\t')[0] for line in completed]
            assert all(value in completed for value in expected), (words, completed)
    else:
        print('Native fish completion probes skipped: fish is not installed')
print('Completion commands: existing candidates, diagnostic-prefix root/verbs/flags, all shell output and available native shells passed')
