#!/usr/bin/env python3
"""LLL-680: a test harness refuses to run lll against the developer's real config.

lll picks its config root as LLL_CONFIG_HOME, then XDG_CONFIG_HOME, then
HOME/.config. A review run once booted `lll up` with XDG_CONFIG_HOME aimed at
the real ~/.config, and the boot replaced the hosted login's web_url there.
Each harness passes the environment its lll processes will get, and this
refuses when that environment reaches the real config.

The real home comes from the password database, never from HOME: HOME is one
of the values being checked. HOME counts only when lll would read it, that
is with neither LLL_CONFIG_HOME nor XDG_CONFIG_HOME set: the e2e suites keep
the real HOME (for warm build caches) while LLL_CONFIG_HOME names their own
root.

Usage from a shell: python3 real_config_guard.py WHO  (checks os.environ)
"""
import os
import pwd
import sys

# Test seam, never set outside a test: names the home the guard treats as the
# developer's, so a test can stand up a fake one and watch the refusal fire.
TEST_REAL_HOME = 'LLL_TEST_GUARD_REAL_HOME'


def real_home():
    fake = os.environ.get(TEST_REAL_HOME, '')
    if fake:
        return fake
    return pwd.getpwuid(os.getuid()).pw_dir


def reaches_real_config(env):
    """The settings in `env` that point lll at the real config, as NAME=VALUE."""
    real_root = os.path.realpath(os.path.join(real_home(), '.config'))

    def is_real(path):
        return bool(path) and os.path.realpath(path) == real_root

    hits = []
    for name in ('LLL_CONFIG_HOME', 'XDG_CONFIG_HOME'):
        value = env.get(name, '').strip()
        if is_real(value):
            hits.append(f'{name}={value}')
    explicit = env.get('LLL_CONFIG_HOME', '').strip() or env.get('XDG_CONFIG_HOME', '').strip()
    home = env.get('HOME', '')
    if not explicit and home and is_real(os.path.join(home, '.config')):
        hits.append(f'HOME={home}')
    return hits


def refuse_real_config(env, who):
    hits = reaches_real_config(env)
    if hits:
        raise SystemExit(
            f'{who}: refusing to run: {", ".join(hits)} points lll at the real config '
            f'{os.path.join(real_home(), ".config", "lll", "lll.toml")}; '
            'point LLL_CONFIG_HOME at a throwaway directory')


if __name__ == '__main__':
    refuse_real_config(os.environ, sys.argv[1] if len(sys.argv) > 1 else 'harness')
