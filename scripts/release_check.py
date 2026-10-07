#!/usr/bin/env python3
"""LLL-620: the automated half of a release. `mise run release-check CUT=<sha>`.

Runs steps 2-4 of docs/release-checklist.md and prints one table row per check,
with its evidence. Any FAIL row exits 1; WARN rows do not. Then prints the
checklist for the manual steps.

Production is only read: a GET of /.well-known/lll, `gh` reads, and CLI reads
(whoami, issue list, label list) with the configured token. Every write goes to
a throwaway `lll up --scratch` server on free ports, under a temp root, with
HOME, XDG_CONFIG_HOME and LLL_CONFIG_HOME pointed inside it (LLL-619).

BOARD_URL=... BOARD_TEAM=... point the hosted reads (step 2) and the security
check (step 3) at another board, with LLL_TOKEN as its token. That exists to
show the security FAIL against a scratch copy without touching the real board.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import http.server
import tomllib
import urllib.error
import urllib.request

from board_startup import wait_for_endpoints

ROOT = Path(__file__).resolve().parent.parent
REPO = 'escherize/lll'
DEPLOY_JOB = 'Deploy verified main to Fly'
GUEST_REFUSAL = 'among the teams you can see'
SKEW_MARK = 'this lll is'
SECURITY_LIMIT = 200
PASS, WARN, FAIL = 'PASS', 'WARN', 'FAIL'
USAGE = 'usage: mise run release-check CUT=<sha> [BOARD_URL=<url> BOARD_TEAM=<key>]'


@dataclass(frozen=True)
class Row:
    step: str
    check: str
    status: str
    evidence: str


# --- pure: parsing and judging -------------------------------------------

def parse_args(argv):
    """KEY=VALUE arguments, as `mise run release-check CUT=<sha>` passes them."""
    args = {}
    for arg in argv:
        key, sep, value = arg.partition('=')
        if not sep or key not in ('CUT', 'BOARD_URL', 'BOARD_TEAM') or not value:
            raise ValueError(f'unexpected argument {arg!r}\n{USAGE}')
        args[key] = value
    if 'CUT' not in args:
        raise ValueError(f'CUT is required\n{USAGE}')
    if ('BOARD_URL' in args) != ('BOARD_TEAM' in args):
        raise ValueError(f'BOARD_URL and BOARD_TEAM go together\n{USAGE}')
    return args


def excerpt(text, limit=180):
    flat = ' '.join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 3] + '...'


def render(rows):
    lines = ['| step | check | result | evidence |', '|---|---|---|---|']
    for r in rows:
        cells = [r.step, r.check, r.status, excerpt(r.evidence, 400)]
        lines.append('| ' + ' | '.join(c.replace('|', '\\|') for c in cells) + ' |')
    return '\n'.join(lines)


def exit_code(rows):
    return 1 if any(r.status == FAIL for r in rows) else 0


def summary(rows):
    counts = {s: sum(r.status == s for r in rows) for s in (PASS, WARN, FAIL)}
    return f'release-check: {counts[PASS]} PASS, {counts[WARN]} WARN, {counts[FAIL]} FAIL -> exit {exit_code(rows)}'


def asset_name(system, machine):
    goos = system.lower()
    goarch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine.lower(), machine.lower())
    return f'lll-{goos}-{goarch}'


def judge_on_main(sha, is_ancestor, main_sha):
    if is_ancestor:
        return Row('2', 'CUT is on origin/main', PASS, f'{sha[:12]} is an ancestor of origin/main {main_sha[:12]}')
    return Row('2', 'CUT is on origin/main', FAIL,
               f'{sha[:12]} is not on origin/main ({main_sha[:12]}); cut from a commit main has merged')


def judge_gate_run(runs, jobs):
    """`runs`: gh run list --json for gate.yml pushes of CUT on main, newest first.
    `jobs`: the jobs of runs[0] (gh run view --json jobs), or None when there is no run."""
    check = "main's gate.yml run for CUT, deploy included"
    if not runs:
        return Row('2', check, FAIL, 'no gate.yml push run on main for CUT: main never ran its gate or deploy on this commit')
    run = runs[0]
    where = f"run {run['databaseId']} {run.get('url', '')}".strip()
    if run.get('status') != 'completed':
        return Row('2', check, FAIL, f"{where} is {run.get('status')}, not completed")
    bad = [f"{j['name']}={j.get('conclusion') or j.get('status')}" for j in jobs if j.get('conclusion') != 'success']
    if bad:
        return Row('2', check, FAIL, f"{where}: {', '.join(bad)}")
    if DEPLOY_JOB not in [j['name'] for j in jobs]:
        return Row('2', check, FAIL, f"{where} has no '{DEPLOY_JOB}' job")
    if run.get('conclusion') != 'success':
        return Row('2', check, FAIL, f"{where} concluded {run.get('conclusion')}")
    return Row('2', check, PASS, f"{where}: {', '.join(j['name'] for j in jobs)} all success")


def judge_discovery(url, body, cut_version):
    check = 'hosted GET /.well-known/lll'
    if not isinstance(body, dict) or body.get('service') != 'lll' or not body.get('version'):
        return Row('2', check, FAIL, f'{url}/.well-known/lll answered {excerpt(json.dumps(body))}')
    if body['version'] != cut_version:
        return Row('2', check, WARN, f"service lll, version {body['version']}; CUT builds {cut_version}")
    return Row('2', check, PASS, f"service lll, version {body['version']} (= CUT)")


def judge_whoami(rc, out, err):
    check = 'hosted lll whoami (configured token)'
    access = re.search(r'^access\s+(.+)$', out, re.M)
    if rc == 0 and access:
        return Row('2', check, PASS, f'access {access[1]}')
    return Row('2', check, FAIL, f'exit {rc}, no access line: {excerpt(out + err)}')


def judge_ok(step, check, argv, rc, out, err):
    if rc == 0:
        return Row(step, check, PASS, f"`lll {' '.join(argv)}` exit 0: {excerpt(out, 100) or '(no output)'}")
    return Row(step, check, FAIL, f"`lll {' '.join(argv)}` exit {rc}: {excerpt(err or out)}")


def judge_guest_refusal(rc, out, err):
    check = 'team-scoped guest refused another team (CUT server)'
    if rc != 0 and GUEST_REFUSAL in err:
        return Row('2', check, PASS, f'exit {rc}: {excerpt(err)}')
    return Row('2', check, FAIL, f"expected non-zero exit naming '{GUEST_REFUSAL}'; got exit {rc}: {excerpt(err or out)}")


def issue_key(issue):
    team = ((issue.get('expand') or {}).get('team') or {}).get('key', '?')
    return f"{team}-{issue.get('number')}"


def judge_security(label_names, in_flight, open_issues):
    """Step 3 from the board's answers. `in_flight` and `open_issues` are issue
    records (lll issue list --json items), or None when the label is missing."""
    if 'security' not in label_names:
        return [Row('3', "label 'security' exists", WARN,
                    f"no 'security' label on this team (labels: {', '.join(sorted(label_names)) or 'none'}); nothing to check")]
    rows = [Row('3', "label 'security' exists", PASS, 'found')]
    truncated = ' (list may be truncated)' if max(len(in_flight), len(open_issues)) >= SECURITY_LIMIT else ''
    if in_flight:
        listed = '; '.join(f"{issue_key(i)} {i.get('state')} '{excerpt(i.get('title', ''), 60)}'" for i in in_flight)
        rows.append(Row('3', 'no security issue in-progress or in-review', FAIL, f'half-landed: {listed}{truncated}'))
    else:
        rows.append(Row('3', 'no security issue in-progress or in-review', PASS, f'none{truncated}'))
    hot = [i for i in open_issues if i.get('priority') in (1, 2)]
    if hot:
        names = {1: 'urgent', 2: 'high'}
        listed = '; '.join(f"{issue_key(i)} {names[i['priority']]} '{excerpt(i.get('title', ''), 60)}'" for i in hot)
        rows.append(Row('3', 'open security issues at urgent/high', WARN, listed + truncated))
    else:
        rows.append(Row('3', 'open security issues at urgent/high', PASS, f'none of {len(open_issues)} open{truncated}'))
    return rows


def judge_commands(check, results, versions):
    """`results`: (argv, rc, out, err) per core command, in order, stopping at the first failure."""
    for argv, rc, out, err in results:
        if rc != 0:
            return Row('4', check, FAIL, f"{versions}: `lll {' '.join(argv)}` exit {rc}: {excerpt(err or out)}")
    names = ', '.join(' '.join(a[:2]) if a[0] == 'issue' else a[0] for a, *_ in results)
    return Row('4', check, PASS, f'{versions}: {names} all exit 0')


def judge_skew(cut_version, newer_err, equal_err):
    check = 'CUT skew warning: newer server warns, equal is silent'
    newer = [line for line in newer_err.splitlines() if SKEW_MARK in line]
    if not newer:
        return Row('4', check, FAIL, f'no warning against a 99.0.0 server: {excerpt(newer_err) or "(stderr empty)"}')
    if SKEW_MARK in equal_err:
        return Row('4', check, FAIL, f'warned at equal version {cut_version}: {excerpt(equal_err)}')
    return Row('4', check, PASS, f'99.0.0: "{excerpt(newer[0], 120)}"; {cut_version}: silent')


def judge_upgrade(out, asset, release_assets):
    check = 'lll upgrade --dry-run (release-download install)'
    want = f'https://github.com/{REPO}/releases/latest/download/{asset}'
    if 'curl -LsSf -o' not in out or want not in out:
        return Row('4', check, FAIL, f'expected a curl of {want}: {excerpt(out)}')
    if release_assets is None:
        return Row('4', check, WARN, f'{excerpt(out)} (latest release unknown; asset not confirmed)')
    if asset not in release_assets:
        return Row('4', check, FAIL, f'suggests {asset}, which the latest release does not publish ({", ".join(release_assets)})')
    return Row('4', check, PASS, f'would curl {want}, an asset of the latest release')


def judge_isolation(before, after, path):
    check = 'real lll config untouched'
    if before == after:
        return Row('4', check, PASS, f'{path}: unchanged; every server ran under the temp root')
    changed = sorted({e[0] for e in set(before or []) ^ set(after or [])})
    return Row('4', check, FAIL, f"{path.parent}: {', '.join(changed) or 'directory'} changed during the run "
                                 '(a leak, or another lll process on this machine wrote it)')


# --- effects --------------------------------------------------------------

def run(argv, env=None, cwd=None, timeout=120):
    try:
        p = subprocess.run([str(a) for a in argv], env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or '', f'timed out after {timeout}s'
    except OSError as e:
        return 127, '', str(e)


def clean_env(home, **extra):
    """No inherited LLL_* or XDG_*; HOME and LLL_CONFIG_HOME inside the temp root."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k not in ('HOME', 'TMPDIR')}
    home.mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(home), LLL_CONFIG_HOME=str(home / 'config'), LC_ALL='C', **extra)
    return env


def real_config_file():
    """Where the CLI reads this machine's config: LLL_CONFIG_HOME, XDG_CONFIG_HOME, ~/.config."""
    base = os.environ.get('LLL_CONFIG_HOME', '').strip() or os.environ.get('XDG_CONFIG_HOME', '').strip() \
        or str(Path.home() / '.config')
    return Path(base) / 'lll' / 'lll.toml'


def fingerprint(config_file):
    """Content hash of the config file plus names and mtimes of its directory."""
    directory = config_file.parent
    if not directory.exists():
        return None
    entries = []
    for p in sorted(directory.rglob('*')):
        stat = p.stat()
        digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ''
        entries.append((str(p.relative_to(directory)), stat.st_mtime_ns, digest))
    return entries


def board_target(args):
    """(url, team, token) for the hosted reads: the checkout's .lll.toml and the
    machine's configured token, unless BOARD_URL/BOARD_TEAM override them."""
    if 'BOARD_URL' in args:
        url, team = args['BOARD_URL'], args['BOARD_TEAM']
    else:
        repo = tomllib.loads((ROOT / '.lll.toml').read_text())
        url, team = repo['url'], repo['team']
    token = os.environ.get('LLL_TOKEN', '').strip()
    if not token:
        path = real_config_file()
        if path.exists():
            token = tomllib.loads(path.read_text()).get('token', '')
    if not token:
        raise RuntimeError(f'no token: set LLL_TOKEN or log in ({real_config_file()})')
    return url.rstrip('/'), team, token


def http_json(url, body=None, token='', method=None, timeout=15):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.load(resp)


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


@contextmanager
def scratch(binary, root):
    """`lll up --scratch` from `binary`: free ports, data under `root`, isolated config."""
    root.mkdir(parents=True)
    env = clean_env(root / 'home', TMPDIR=str(root))
    log = root / 'boot.log'
    with log.open('w') as output:
        process = subprocess.Popen([str(binary), 'up', '--scratch', '--no-open'], cwd=root, env=env,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        wait_for_endpoints(log, timeout=60)
        text = log.read_text()
        config = tomllib.loads((Path(re.search(r'^scratch config (.+)$', text, re.M)[1]) / 'lll' / 'lll.toml').read_text())
        admin = re.search(r'^scratch admin  (\S+) / (\S+) ', text, re.M)
        data = Path(re.search(r'^scratch data   (.+)$', text, re.M)[1])
        if not data.resolve().is_relative_to(root.resolve()):
            raise AssertionError(f'scratch data {data} escaped the temp root {root}')
        yield {'url': config['url'], 'team': config['team'], 'token': config['token'],
               'admin': (admin[1], admin[2]), 'version': re.search(r'^lll    (\S+)$', text, re.M)[1]}
    finally:
        stop(process)


def client_env(home, server):
    return clean_env(home, LLL_URL=server['url'], LLL_TEAM=server['team'], LLL_TOKEN=server['token'])


def core_commands(binary, server, workdir):
    """whoami, issue list, create, comment, claim, release; stops at the first failure."""
    env = client_env(workdir / 'home', server)
    results = []
    for argv in (['whoami'], ['issue', 'list', '--limit', '5'], ['issue', 'create', '-t', 'release-check probe']):
        results.append((argv, *run([binary, *argv], env=env, cwd=workdir, timeout=60)))
        if results[-1][1] != 0:
            return results
    key = re.search(rf"\b{re.escape(server['team'])}-\d+\b", results[-1][2])
    if not key:
        results[-1] = (results[-1][0], 1, results[-1][2], 'create printed no issue key: ' + results[-1][2])
        return results
    for argv in (['issue', 'comment', key[0], '-b', 'release-check probe'],
                 ['issue', 'claim', key[0]], ['issue', 'release', key[0]]):
        results.append((argv, *run([binary, *argv], env=env, cwd=workdir, timeout=60)))
        if results[-1][1] != 0:
            return results
    return results


def guest_refusal(binary, server, workdir):
    """A guest scoped to the scratch team asks for another team."""
    api = server['url']
    email, password = server['admin']
    su = http_json(f'{api}/api/collections/_superusers/auth-with-password', {'identity': email, 'password': password})['token']
    teams = http_json(f'{api}/api/collections/teams/records', token=su)['items']
    home_team = next(t for t in teams if t['key'] == server['team'])
    http_json(f'{api}/api/collections/teams/records', {'key': 'OTHER', 'name': 'Other'}, su)
    guest = {'name': 'guest', 'email': 'guest@example.invalid', 'password': 'release-check-guest',
             'passwordConfirm': 'release-check-guest', 'kind': 'person', 'scope': 'teams',
             'teams': [home_team['id']], 'mode': 'rw'}
    http_json(f'{api}/api/collections/members/records', guest, su)
    token = http_json(f'{api}/api/collections/members/auth-with-password',
                      {'identity': guest['email'], 'password': guest['password']})['token']
    env = client_env(workdir / 'home', dict(server, token=token))
    return judge_guest_refusal(*run([binary, 'issue', 'list', '--team', 'OTHER'], env=env, cwd=workdir, timeout=60))


def stub_discovery(version):
    body_for = {'/.well-known/lll': json.dumps({'service': 'lll', 'web_url': '.', 'version': version}).encode()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = body_for.get(self.path, b'{"items":[],"totalItems":0,"page":1,"perPage":200}')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def skew_stderr(binary, version, workdir):
    server = stub_discovery(version)
    try:
        env = clean_env(workdir / 'home', LLL_URL=f'http://127.0.0.1:{server.server_port}',
                        LLL_TOKEN='release-check', LLL_TEAM='SKEW')
        rc, out, err = run([binary, 'api', 'GET', '/api/collections/teams/records'], env=env, cwd=workdir, timeout=30)
        if rc != 0:
            raise RuntimeError(f'lll api against a {version} stub exited {rc}: {excerpt(err)}')
        return err
    finally:
        server.shutdown()


def latest_release(dest, asset):
    """(tag, binary path, asset names) or raise with the reason."""
    rc, out, err = run(['gh', 'release', 'view', '-R', REPO, '--json', 'tagName,assets'], timeout=60)
    if rc != 0:
        raise RuntimeError(f'gh release view: {excerpt(err or out)}')
    info = json.loads(out)
    names = [a['name'] for a in info['assets']]
    if asset not in names:
        raise RuntimeError(f"{info['tagName']} publishes no {asset} ({', '.join(names)})")
    dest.mkdir(parents=True)
    rc, out, err = run(['gh', 'release', 'download', info['tagName'], '-R', REPO, '--pattern', asset, '-D', dest], timeout=300)
    if rc != 0:
        raise RuntimeError(f"gh release download {info['tagName']}: {excerpt(err or out)}")
    path = dest / asset
    path.chmod(0o755)
    return info['tagName'], path, names


def build_cut(sha, tmp):
    """Build CUT in a detached worktree under `tmp`, never in this checkout."""
    src = tmp / 'cut-src'
    rc, out, err = run(['git', '-C', ROOT, 'worktree', 'add', '--detach', src, sha], timeout=120)
    if rc != 0:
        raise RuntimeError(f'git worktree add: {excerpt(err)}')
    try:
        rc, out, err = run(['lis', 'build'], env=dict(os.environ, LC_ALL='C'), cwd=src, timeout=900)
        if rc != 0:
            raise RuntimeError(f'lis build exit {rc}: {excerpt(out + err, 300)}')
        binary = tmp / 'bin' / 'lll-cut'
        binary.parent.mkdir()
        shutil.copy2(src / 'target/.lisette/bin/lll', binary)
        version = (tomllib.loads((src / 'lisette.toml').read_text())['project']['version'])
        return binary, version
    finally:
        run(['git', '-C', ROOT, 'worktree', 'remove', '--force', src], timeout=120)


def attempt(rows, step, check, fn):
    """Append fn()'s row(s); an exception is that check's FAIL, not a crash."""
    try:
        result = fn()
    except Exception as e:  # noqa: BLE001 - every failure becomes evidence
        result = Row(step, check, FAIL, f'{type(e).__name__}: {excerpt(e, 300)}')
    rows.extend(result if isinstance(result, list) else [result])
    return result


def lll_json(binary, env, cwd, *argv):
    rc, out, err = run([binary, *argv, '--json'], env=env, cwd=cwd, timeout=60)
    if rc != 0:
        raise RuntimeError(f"`lll {' '.join(argv)} --json` exit {rc}: {excerpt(err or out)}")
    return json.loads(out)['items']


def main(argv):
    try:
        args = parse_args(argv)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    rows = []
    config_file = real_config_file()
    before = fingerprint(config_file)

    rc, out, err = run(['git', '-C', ROOT, 'rev-parse', '--verify', args['CUT'] + '^{commit}'])
    if rc != 0:
        rows.append(Row('2', 'CUT resolves to a commit', FAIL, f"{args['CUT']}: {excerpt(err)}"))
        print(render(rows))
        print(summary(rows))
        return exit_code(rows)
    sha = out.strip()

    with tempfile.TemporaryDirectory(prefix='lll-release-check-') as directory:
        tmp = Path(directory).resolve()

        def on_main():
            rc, _, err = run(['git', '-C', ROOT, 'fetch', '--quiet', 'origin', 'main'], timeout=120)
            if rc != 0:
                raise RuntimeError(f'git fetch origin main: {excerpt(err)}')
            main_sha = run(['git', '-C', ROOT, 'rev-parse', 'origin/main'])[1].strip()
            is_ancestor = run(['git', '-C', ROOT, 'merge-base', '--is-ancestor', sha, 'origin/main'])[0] == 0
            return judge_on_main(sha, is_ancestor, main_sha)
        attempt(rows, '2', 'CUT is on origin/main', on_main)

        def gate_run():
            rc, out, err = run(['gh', 'run', 'list', '-R', REPO, '--workflow', 'gate.yml', '--commit', sha,
                                '--event', 'push', '--branch', 'main',
                                '--json', 'databaseId,status,conclusion,url,createdAt'], timeout=60)
            if rc != 0:
                raise RuntimeError(f'gh run list: {excerpt(err)}')
            runs = sorted(json.loads(out), key=lambda r: r['createdAt'], reverse=True)
            jobs = None
            if runs:
                rc, out, err = run(['gh', 'run', 'view', str(runs[0]['databaseId']), '-R', REPO, '--json', 'jobs'], timeout=60)
                if rc != 0:
                    raise RuntimeError(f'gh run view: {excerpt(err)}')
                jobs = json.loads(out)['jobs']
            return judge_gate_run(runs, jobs)
        attempt(rows, '2', "main's gate.yml run for CUT, deploy included", gate_run)

        try:
            cut_bin, cut_version = build_cut(sha, tmp)
            rows.append(Row('2', 'build CUT', PASS, f'{sha[:12]} -> lll {cut_version} (temp worktree, removed)'))
        except Exception as e:  # noqa: BLE001
            cut_bin, cut_version = None, '?'
            rows.append(Row('2', 'build CUT', FAIL, excerpt(e, 300)))

        def needs_cut(step, check, fn):
            if cut_bin is None:
                rows.append(Row(step, check, FAIL, 'no CUT binary (build failed)'))
            else:
                attempt(rows, step, check, fn)

        hosted_dir = tmp / 'hosted'
        hosted_dir.mkdir()
        try:
            url, team, token = board_target(args)
        except Exception as e:  # noqa: BLE001
            url = team = token = None
            rows.append(Row('2', 'hosted board target', FAIL, excerpt(e)))
        if url:
            attempt(rows, '2', 'hosted GET /.well-known/lll',
                    lambda: judge_discovery(url, http_json(url + '/.well-known/lll'), cut_version))
            hosted_env = clean_env(hosted_dir / 'home', LLL_URL=url, LLL_TEAM=team, LLL_TOKEN=token)
            needs_cut('2', 'hosted lll whoami (configured token)',
                      lambda: judge_whoami(*run([cut_bin, 'whoami'], env=hosted_env, cwd=hosted_dir, timeout=60)))
            needs_cut('2', 'hosted lll issue list --limit 1',
                      lambda: judge_ok('2', 'hosted lll issue list --limit 1', ['issue', 'list', '--limit', '1'],
                                       *run([cut_bin, 'issue', 'list', '--limit', '1'], env=hosted_env, cwd=hosted_dir, timeout=60)))

        def security():
            labels = [label['name'] for label in lll_json(cut_bin, hosted_env, hosted_dir, 'label', 'list')]
            if 'security' not in labels:
                return judge_security(labels, [], [])
            limit = ['--limit', str(SECURITY_LIMIT)]
            in_flight = lll_json(cut_bin, hosted_env, hosted_dir, 'issue', 'list', '--label', 'security',
                                 '--state', 'in-progress', '--state', 'in-review', *limit)
            open_issues = lll_json(cut_bin, hosted_env, hosted_dir, 'issue', 'list', '--label', 'security',
                                   '--state', 'backlog', '--state', 'todo', '--state', 'in-progress',
                                   '--state', 'in-review', *limit)
            return judge_security(labels, in_flight, open_issues)
        if url:
            needs_cut('3', 'security issues on the board', security)
        else:
            rows.append(Row('3', 'security issues on the board', FAIL, 'no board target'))

        asset = asset_name(platform.system(), platform.machine())
        try:
            release = latest_release(tmp / 'release', asset)
        except Exception as e:  # noqa: BLE001
            release, release_why = None, excerpt(e)

        old_on_new = 'old client (latest release) on CUT server'
        new_on_old = 'CUT client on old server (latest release)'
        guest_check = 'team-scoped guest refused another team (CUT server)'
        if cut_bin is None:
            rows.append(Row('2', guest_check, FAIL, 'no CUT binary (build failed)'))
            rows.append(Row('4', old_on_new, FAIL, 'no CUT binary (build failed)'))
        else:
            try:
                with scratch(cut_bin, tmp / 'srv-cut') as server:
                    attempt(rows, '2', guest_check, lambda: guest_refusal(cut_bin, server, tmp / 'guest'))
                    if release is None:
                        rows.append(Row('4', old_on_new, WARN, f'no release binary: {release_why}'))
                    else:
                        tag, rel_bin, _ = release
                        attempt(rows, '4', old_on_new, lambda: judge_commands(
                            old_on_new, core_commands(rel_bin, server, tmp / 'old-client'),
                            f"client {tag}, server {server['version']} @ {sha[:12]}"))
            except Exception as e:  # noqa: BLE001
                why = f'CUT scratch server: {type(e).__name__}: {excerpt(e, 300)}'
                rows.extend(r for r in (Row('2', guest_check, FAIL, why), Row('4', old_on_new, FAIL, why))
                            if r.check not in [x.check for x in rows])

        if release is None:
            rows.append(Row('4', new_on_old, WARN, f'no release binary: {release_why}'))
        else:
            def on_old_server():
                tag, rel_bin, _ = release
                with scratch(rel_bin, tmp / 'srv-old') as server:
                    return judge_commands(new_on_old, core_commands(cut_bin, server, tmp / 'new-client'),
                                          f"client {cut_version} @ {sha[:12]}, server {tag}")
            needs_cut('4', new_on_old, on_old_server)

        needs_cut('4', 'CUT skew warning: newer server warns, equal is silent',
                  lambda: judge_skew(cut_version, skew_stderr(cut_bin, '99.0.0', tmp / 'skew-newer'),
                                     skew_stderr(cut_bin, cut_version, tmp / 'skew-equal')))

        def upgrade():
            installed = tmp / 'upgrade-home' / 'bin' / 'lll'
            installed.parent.mkdir(parents=True)
            shutil.copy2(cut_bin, installed)
            rc, out, err = run([installed, 'upgrade', '--dry-run'], env=clean_env(tmp / 'upgrade-home'),
                               cwd=tmp / 'upgrade-home', timeout=30)
            if rc != 0:
                return Row('4', 'lll upgrade --dry-run (release-download install)', FAIL, f'exit {rc}: {excerpt(err)}')
            return judge_upgrade(out, asset, release[2] if release else None)
        needs_cut('4', 'lll upgrade --dry-run (release-download install)', upgrade)

    rows.append(judge_isolation(before, fingerprint(config_file), config_file))
    rows.sort(key=lambda r: r.step)
    print(render(rows))
    print()
    print(summary(rows))
    print()
    print((ROOT / 'docs/release-checklist.md').read_text())
    return exit_code(rows)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
