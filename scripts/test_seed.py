#!/usr/bin/env python3
"""Run `mise run seed`'s script and prove it seeded something (LLL-385).

The gate could not see this path at all - it depends on build, test and e2e,
and none of them mention seed. So `mise run seed` died at its first issue
create for five days while every gate stayed green (LLL-377), and it was only
noticed when somebody wanted a board with data on it to look at.

That matters more than a demo script usually would: README points at it for the
board screenshot, the lll skill names it, and it is the only way to see the UI
with realistic data, which design work and the landing page both need.

What this asserts is deliberately shallow - that seed EXITS ZERO and reports a
non-zero count of issues, projects and labels. It is a smoke test for a fixture
script, not a second e2e suite, and the cost has to stay near the ten seconds
seed already takes or the gate pays for it on every run.

Two things it must not do, both of which would be worse than no check:

  * clobber a developer's running demo board. seed.sh wipes its data directory
    on each run, so this points LLL_DEMO_DIR at a temp directory of its own.
  * leave a server behind. seed.sh ends with `wait "$UP_PID"` - it hands the
    terminal to the board on purpose - so this kills the whole process group
    and waits for it to actually be gone.
"""
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "scripts" / "seed.sh"
# seed.sh builds nothing; the caller (e2e.sh) has already run `lis build`.
BANNER = re.compile(
    r"seeded (\d+) issues, (\d+) projects, (\d+) labels, (\d+) members", re.I
)
DEADLINE = 180  # generous: a cold PocketBase boot on a loaded CI runner


def main() -> None:
    demo = Path(tempfile.mkdtemp(prefix="lll-seed-check-"))
    env = dict(os.environ, LLL_DEMO_DIR=str(demo))
    # Whatever the caller configured must not steer the fixture, the same
    # bargain e2e_begin makes (LLL-394, LLL-400).
    for leak in ("LLL_ME", "LLL_TOKEN", "LLL_URL", "LLL_TEAM", "LLL_CONFIG_HOME",
                 "LLL_BOARD_TOKEN"):
        env.pop(leak, None)
    # LLL-423: XDG_CONFIG_HOME is POISONED rather than removed. Stripping it
    # asserted nothing and hid a real failure: seed.sh moved HOME and stopped
    # there, so on any machine exporting XDG_CONFIG_HOME (a common dotfiles
    # setting) seed read the developer's own lll.toml and died on its hosted
    # token against a server that had never issued it. The gate stayed green
    # because the gate had unset the variable. A config root that exists and
    # must be ignored is the only version of this check worth running.
    poison = demo.parent / f"{demo.name}-config"
    (poison / "lll").mkdir(parents=True, exist_ok=True)
    (poison / "lll" / "lll.toml").write_text(
        'url = "http://127.0.0.1:1"\ntoken = "poison-not-a-real-token"\n'
        'team = "POISON"\nme = "poison"\n'
    )
    env["XDG_CONFIG_HOME"] = str(poison)

    proc = subprocess.Popen(
        ["bash", str(SEED)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,   # its own group, so the board dies with it
    )
    seen, counts, started = [], None, time.monotonic()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            seen.append(line)
            m = BANNER.search(line)
            if m:
                counts = [int(g) for g in m.groups()]
                break
            if time.monotonic() - started > DEADLINE:
                break
            if proc.poll() is not None:
                break
    finally:
        _reap(proc)
        shutil.rmtree(demo, ignore_errors=True)
        shutil.rmtree(poison, ignore_errors=True)

    transcript = "".join(seen[-25:])
    if counts is None:
        # Name which of the two happened. Seed dying and seed hanging want
        # different investigations, and a message that blurs them sends the
        # reader looking for a timeout that never occurred.
        why = (
            f"seed exited {proc.returncode} without reporting what it seeded"
            if proc.returncode not in (None, 0)
            else f"seed reported nothing within {DEADLINE}s"
        )
        sys.exit(f"{why}. Last lines:\n{transcript}")
    issues, projects, labels, members = counts
    if min(issues, projects, labels, members) <= 0:
        sys.exit(f"seed reported an empty fixture set: {counts}\n{transcript}")
    if demo.exists():
        sys.exit(f"seed left its data directory behind at {demo}")
    print(
        f"Seed: {issues} issues, {projects} projects, {labels} labels, "
        f"{members} members into a throwaway board, then torn down"
    )


def _reap(proc: subprocess.Popen) -> None:
    """seed.sh blocks on its server, so the group has to go, not just the shell."""
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=10)
    if proc.stdout:
        proc.stdout.close()


if __name__ == "__main__":
    main()
