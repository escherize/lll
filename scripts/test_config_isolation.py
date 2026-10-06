#!/usr/bin/env python3
"""LLL-619: an e2e suite's `lll up` must not write the developer's config.

config.lis picks the config root as LLL_CONFIG_HOME, then XDG_CONFIG_HOME, then
HOME/.config, and `lll up` saves its endpoint there as web_url. A developer
shell that exports XDG_CONFIG_HOME made gate runs rewrite the real
~/.config/lll/lll.toml while HOME pointed at a scratch directory.

This runs lib.sh's e2e_begin with both variables aimed at a sentinel and HOME
aimed at a stand-in for the developer's home, then boots `lll up` BEFORE
e2e_pin_home. That is the window e2e_web.sh and e2e_up.sh run in when e2e.sh
hands them HOME=$E2E_REAL_HOME so their `lis build` keeps a warm cache. The
boot must write its web_url under the suite's scratch home and nowhere else.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
repo = Path(__file__).resolve().parent.parent

# Boots one `lll up` on free ports, waits for its endpoints, stops it, and
# prints the config file it wrote. Same boot e2e_up.sh does, minus the pin.
DRIVER = r'''
set -euo pipefail
. "$REPO/scripts/lib.sh"
e2e_begin
cleanup() { e2e_diagnose "$1"; e2e_reap "${UP_PID:-}"; e2e_end; }
e2e_trap_cleanup cleanup
UP_LOG="$DATA_DIR/up.log"
E2E_LOGS="$UP_LOG"
DB_PORT=$(free_port 20000 39999)
WEB_PORT=$(free_port 40000 59999)
env -u LLL_TOKEN LLL_URL="http://127.0.0.1:$DB_PORT" LLL_TEAM=ISO USER=isolation \
  "$LLL" up --no-open --port "$WEB_PORT" --pb-dir "$DATA_DIR/pb_data" >"$UP_LOG" 2>&1 &
UP_PID=$!
python3 "$REPO/scripts/board_startup.py" --endpoints "$UP_LOG" >/dev/null \
  || fail "lll up did not announce its endpoints"
written="$E2E_HOME/.config/lll/lll.toml"
for _ in $(seq 1 50); do
  grep -q '^web_url' "$written" 2>/dev/null && break
  sleep 0.1
done
cat "$written" 2>/dev/null || true
'''


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob('*'))}


with tempfile.TemporaryDirectory(prefix='lll-619-') as directory:
    base = Path(directory)
    sentinel = base / 'sentinel'
    (sentinel / 'lll').mkdir(parents=True)
    (sentinel / 'lll' / 'lll.toml').write_text('web_url = "http://sentinel.invalid"\n')
    home = base / 'developer-home'
    home.mkdir()
    before = snapshot(sentinel)

    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(sentinel),
               LLL_CONFIG_HOME=str(sentinel), REPO=str(repo), LLL=binary)
    run = subprocess.run(['bash', '-c', DRIVER], env=env, capture_output=True,
                         text=True, timeout=120)
    if run.returncode != 0:
        sys.exit(f'isolation driver exited {run.returncode}:\n{run.stdout}\n{run.stderr}')
    after = snapshot(sentinel)
    if after != before:
        sys.exit(f'lll up wrote the XDG_CONFIG_HOME/LLL_CONFIG_HOME sentinel: {sorted(after)}\n'
                 f'{(sentinel / "lll" / "lll.toml").read_text()}')
    leaked = sorted(str(p.relative_to(home)) for p in home.rglob('*'))
    if leaked:
        sys.exit(f'lll up wrote under the inherited HOME: {leaked}')
    # Without this the test would pass on a boot that wrote nothing at all.
    if 'web_url' not in run.stdout:
        sys.exit(f'lll up wrote no web_url under the suite scratch home:\n{run.stdout}\n{run.stderr}')

print('Config isolation: e2e lll up wrote only the suite scratch home, never the inherited XDG_CONFIG_HOME, LLL_CONFIG_HOME or HOME.')
