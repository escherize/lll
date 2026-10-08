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
import pwd
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
if [ -n "${PRESEED:-}" ]; then printf '%s' "$PRESEED" >"$E2E_HOME/.config/lll/lll.toml"; fi
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
grep '^board  web_url' "$UP_LOG" || true
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

# LLL-680: the same boot beside a home config that names a hosted server keeps
# that server's web_url, and says so.
hosted = 'url = "https://hosted.lll.invalid"\nweb_url = "https://board.hosted.lll.invalid"\n'
env = dict(os.environ, REPO=str(repo), LLL=binary, PRESEED=hosted)
run = subprocess.run(['bash', '-c', DRIVER], env=env, capture_output=True, text=True, timeout=120)
if run.returncode != 0:
    sys.exit(f'hosted-config driver exited {run.returncode}:\n{run.stdout}\n{run.stderr}')
if not run.stdout.startswith(hosted) or 'web_url unchanged' not in run.stdout:
    sys.exit(f'lll up rewrote a hosted home config, or did not say it kept it:\n{run.stdout}')

# LLL-680: the harnesses refuse to run when the environment their lll gets
# reaches the developer's real config. A fake "real home" stands in through
# the guard's test seam; nothing here touches the actual one.
sys.path.insert(0, str(repo / 'scripts'))
import real_config_guard  # noqa: E402
from agent_dx_fleet import clean_env  # noqa: E402

with tempfile.TemporaryDirectory(prefix='lll-680-') as directory:
    base = Path(directory)
    fake_real = base / 'real-home'
    (fake_real / '.config').mkdir(parents=True)
    other = base / 'other'
    other.mkdir()
    (base / 'link-to-config').symlink_to(fake_real / '.config')
    os.environ[real_config_guard.TEST_REAL_HOME] = str(fake_real)
    try:
        reaches = real_config_guard.reaches_real_config
        assert reaches({'HOME': str(fake_real)}) == [f'HOME={fake_real}']
        assert reaches({'HOME': str(other), 'XDG_CONFIG_HOME': str(fake_real / '.config')})
        assert reaches({'HOME': str(other), 'LLL_CONFIG_HOME': str(fake_real / '.config') + '/'})
        assert reaches({'HOME': str(other), 'LLL_CONFIG_HOME': str(base / 'link-to-config')})
        # A shadowed real HOME is what the e2e suites run with before the pin.
        assert reaches({'HOME': str(fake_real), 'LLL_CONFIG_HOME': str(other)}) == []
        assert reaches({'HOME': str(other)}) == []

        # The agent-dx fleet wrapper's environment: its config root is the
        # worker's home/config, here the fake real home's .config by symlink.
        worker_home = base / 'worker-home'
        (worker_home / 'config').mkdir(parents=True)
        fleet_real = base / 'fleet-real-home'
        fleet_real.mkdir()
        (fleet_real / '.config').symlink_to(worker_home / 'config')
        os.environ[real_config_guard.TEST_REAL_HOME] = str(fleet_real)
        try:
            clean_env(worker_home)
        except SystemExit as refused:
            assert 'agent_dx_fleet: refusing to run' in str(refused), refused
        else:
            sys.exit('agent_dx_fleet.clean_env accepted the real home')
        os.environ[real_config_guard.TEST_REAL_HOME] = str(fake_real)
        clean_env(other)

        # lib.sh: e2e_pin_home hands lll HOME, which here is the fake real one.
        driver = ('set -euo pipefail\n. "$REPO/scripts/lib.sh"\ne2e_begin\n'
                  'trap \'cd / && rm -rf "$DATA_DIR"\' EXIT\n'
                  'export LLL_TEST_GUARD_REAL_HOME="$E2E_HOME"\ne2e_pin_home\n'
                  'echo "pinned without refusing"\n')
        run = subprocess.run(['bash', '-c', driver], env=dict(os.environ, REPO=str(repo)),
                             capture_output=True, text=True, timeout=60)
        if run.returncode == 0 or 'e2e_pin_home: refusing to run' not in run.stderr:
            sys.exit(f'e2e_pin_home did not refuse the real home:\n{run.stdout}\n{run.stderr}')
    finally:
        del os.environ[real_config_guard.TEST_REAL_HOME]

    # Without the seam the guard compares against the account's home from the
    # password database: a HOME elsewhere passes, and a config root at the
    # real home is refused whatever HOME says. Only the guard runs here.
    guard = [sys.executable, str(repo / 'scripts' / 'real_config_guard.py'), 'probe']
    clean = {k: v for k, v in os.environ.items()
             if k not in ('LLL_CONFIG_HOME', 'XDG_CONFIG_HOME', real_config_guard.TEST_REAL_HOME)}
    assert subprocess.run(guard, env=dict(clean, HOME=str(other))).returncode == 0
    real = pwd.getpwuid(os.getuid()).pw_dir
    refused = subprocess.run(guard, env=dict(clean, HOME=str(other), XDG_CONFIG_HOME=real + '/.config'),
                             capture_output=True, text=True)
    assert refused.returncode != 0 and 'XDG_CONFIG_HOME=' in refused.stderr, refused

print('Config isolation: e2e lll up wrote only the suite scratch home, never the inherited XDG_CONFIG_HOME, LLL_CONFIG_HOME or HOME; the harness guard refuses an environment that reaches the real config.')

