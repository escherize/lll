"""Every `lll` example in README.md and docs/index.html runs as written.

A newcomer copies these commands before reading anything else, so an example
that fails is the first thing lll teaches them. This runs each document, top
to bottom, as one newcomer would: a fresh HOME, no LLL_* settings from the
calling shell, the binary under test on PATH as `lll`, and a scratch board
that the document's own `lll up` line starts.

What runs: README.md's fenced `sh`/`bash` blocks and docs/index.html's terminal
panes (`<span class="cmd">`), every line of each block that has at least one
line running `lll` (after any VAR=value prefix, or a shell operator). Lines run in order in
one bash process, so a `cd` carries into later blocks the way it does for a
reader. Each must exit 0, pipelines included. A line running `lll up` starts
in the background and the check waits for its banner. The run is its own
process group, stopped as a whole afterwards, so no server outlives it.
`brew`, `curl`, `wget` and `sudo` are stubs that refuse.
Prose mentions (`lll attach --key KEY` inside a sentence) are not run.

A block that cannot run here (a hosted url, administrator credentials, a
stream that never ends) is marked skip, with its reason, in the document
source just before it:

    <!-- example-check: skip: needs a hosted server -->

Two deliberate departures from "as written": LLL_URL points the first
`lll up` at a free port, so the check never reuses a server already running
on :8090; and `open`/`xdg-open` are stubs, so `lll board -w` opens nothing.
docs/index.html shows `lll up` last but needs its board first, so that
pane runs first.
"""
import html
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time

binary = str(Path(sys.argv[1]).resolve())
ROOT = Path(__file__).resolve().parents[1]
SKIP = re.compile(r'<!--\s*example-check:\s*skip:\s*(.+?)\s*-->')
# An lll command anywhere a command can start: the line's head, or after
# a shell operator, with any VAR=value prefix.
LLL_LINE = re.compile(r'(?:^|&&|\|\||;|\||\$\()\s*(?:[A-Z_][A-Z0-9_]*=\S+\s+)*lll(?:\s|$)')
UP_LINE = re.compile(r'^(?:[A-Z_][A-Z0-9_]*=\S+\s+)*lll up(?:\s|$)')


def logical_lines(text):
    """Join backslash continuations; drop blank lines and whole-line comments."""
    out, pending = [], ''
    for raw in text.splitlines():
        line = pending + raw.strip()
        if line.endswith('\\'):
            pending = line[:-1] + ' '
            continue
        pending = ''
        if line and not line.startswith('#'):
            out.append(line)
    return out


def readme_blocks(text):
    """(name, lines, skip reason or None) per fenced sh block."""
    blocks = []
    for match in re.finditer(r'^```(?:sh|bash|shell|console)\n(.*?)^```', text, re.M | re.S):
        before = text[:match.start()].rstrip().splitlines()
        reason = SKIP.search(before[-1]) if before else None
        line_no = text[:match.start()].count('\n') + 1
        blocks.append((f'README.md:{line_no}', logical_lines(match.group(1)),
                       reason.group(1) if reason else None))
    return blocks


def landing_blocks(text):
    """(name, lines, skip reason or None) per terminal pane; `lll up` panes first."""
    blocks = []
    for match in re.finditer(r'<div class="term(?: [^"]*)?">(.*?)</pre></div>', text, re.S):
        before = text[:match.start()].rstrip().splitlines()
        reason = SKIP.search(before[-1]) if before else None
        cmds = [html.unescape(re.sub(r'<[^>]+>', '', c))
                for c in re.findall(r'<span class="cmd">(.*?)</span>', match.group(1), re.S)]
        line_no = text[:match.start()].count('\n') + 1
        blocks.append((f'docs/index.html:{line_no}', [l for c in cmds for l in logical_lines(c)],
                       reason.group(1) if reason else None))
    return sorted(blocks, key=lambda b: not any(UP_LINE.match(l) for l in b[1]))


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def script_for(blocks, work):
    """One bash script running every runnable line, reporting each failure."""
    # pipefail: 'lll issue view NOPE-1 | cat' must fail like the lll in it.
    # Every process here, servers included, is in the run's own process
    # group, which run_document stops as a whole.
    out = ['set -o pipefail', 'fails=0']
    n = 0
    for name, lines, reason in blocks:
        if not any(LLL_LINE.search(l) for l in lines):
            continue
        if reason:
            out.append(f'echo {shlex.quote(f"skip {name}: {reason}")}')
            continue
        for line in lines:
            n += 1
            shown = shlex.quote(f'{name}: {line}')
            out.append(f'echo "+ "{shown}')
            if UP_LINE.match(line):
                log = shlex.quote(str(work / f'up-{n}.log'))
                out += [
                    # Braces, so a trailing '# comment' cannot swallow the '&'.
                    '{', line, f'}} > {log} 2>&1 &',
                    'up_ok=0',
                    'for _ in $(seq 1 120); do',
                    f'  if grep -q "^board  login" {log}; then up_ok=1; break; fi',
                    '  kill -0 $! 2>/dev/null || break',
                    '  sleep 0.25',
                    'done',
                    f'if [ $up_ok -ne 1 ]; then echo "FAIL (no board banner): "{shown}; cat {log}; fails=$((fails+1)); fi',
                ]
                continue
            out += [
                line,
                f'rc=$?; if [ $rc -ne 0 ]; then echo "FAIL rc=$rc: "{shown}; fails=$((fails+1)); fi',
            ]
    out.append('echo "$fails failed"; [ $fails -eq 0 ]')
    return '\n'.join(out) + '\n', n


def run_document(label, blocks):
    with tempfile.TemporaryDirectory(prefix='lll-doc-examples-') as tmp:
        work = Path(tmp)
        home = work / 'home'
        stubs = work / 'bin'
        start = home / 'start'
        for d in (home, stubs, start):
            d.mkdir(parents=True)
        (stubs / 'lll').symlink_to(binary)
        for opener in ('open', 'xdg-open'):
            stub = stubs / opener
            stub.write_text('#!/bin/sh\necho "(would open $1)"\n')
            stub.chmod(0o755)
        # Installers never run on the host, whatever a document grows.
        for refused in ('brew', 'curl', 'wget', 'sudo'):
            stub = stubs / refused
            stub.write_text(f'#!/bin/sh\necho "doc check: refusing to run {refused}" >&2\nexit 97\n')
            stub.chmod(0o755)
        script, count = script_for(blocks, work)
        (work / 'examples.sh').write_text(script)
        env = {
            'HOME': str(home),
            'USER': 'newbie',
            'PATH': f'{stubs}:/usr/bin:/bin:/usr/sbin:/sbin',
            'LANG': os.environ.get('LANG', 'en_US.UTF-8'),
            'TMPDIR': str(work),
            'LLL_URL': f'http://127.0.0.1:{free_port()}',
            'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_AUTHOR_NAME': 'newbie', 'GIT_AUTHOR_EMAIL': 'newbie@example.com',
            'GIT_COMMITTER_NAME': 'newbie', 'GIT_COMMITTER_EMAIL': 'newbie@example.com',
        }
        log = work / 'examples.log'
        with open(log, 'w') as sink:
            proc = subprocess.Popen(['bash', str(work / 'examples.sh')], cwd=start, env=env,
                                    stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                returncode = proc.wait(timeout=300)
            except subprocess.TimeoutExpired:
                returncode = None
            finally:
                stop_group(proc.pid)
        output = log.read_text()
        if returncode != 0:
            print(output)
        assert returncode is not None, f'{label}: timed out after 300s (output above)'
        assert returncode == 0, f'{label}: example lines failed (output above)'
        skipped = output.count('\nskip ') + output.startswith('skip ')
        print(f'{label}: {count} example lines ran, {skipped} blocks skipped with a reason')


def stop_group(pgid):
    """Stop the run's process group: bash, and every `lll up` it started."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        for _ in range(40):
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.25)


def main():
    readme = readme_blocks((ROOT / 'README.md').read_text())
    landing = landing_blocks((ROOT / 'docs' / 'index.html').read_text())
    assert readme and landing, 'no examples found; did the block markup change?'
    run_document('README.md', readme)
    run_document('docs/index.html', landing)


main()
