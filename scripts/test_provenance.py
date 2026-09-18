#!/usr/bin/env python3
"""Creation context through real CLI/API/board writes and the export mirror."""
import base64
import html
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.error
import urllib.request

from browser_session import new_session, open_session, require_result

binary, api, board = sys.argv[1:]
binary = str(Path(binary).resolve())
root = Path(__file__).resolve().parent.parent
token = os.environ['LLL_TOKEN']
subject = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))['id']


def request(path, body=None, method=None):
    req = urllib.request.Request(api + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


member = request('/api/collections/members/records/' + subject)
team = request('/api/collections/teams/records', {'key': 'PROV168', 'name': 'Provenance'})
prefix = '/api/collections/issues/records'
with tempfile.TemporaryDirectory(prefix='lll-provenance-') as directory:
    base = Path(directory)
    repo = base / '一 checkout'
    repo.mkdir()
    env = dict(os.environ, LLL_TEAM='PROV168', LLL_AGENT='provenance-test')

    def cli(*args, cwd=repo):
        result = subprocess.run([binary, *args], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def git(*args):
        return subprocess.run(['git', *args], cwd=repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    git('init', '-b', 'provenance')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.test')
    git('-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'fixture')
    created = json.loads(cli('issue', 'create', 'Ambient context', '--json'))
    assert created['creator'] == subject
    assert created['expand']['creator']['name'] == member['name']
    assert created['origin'] == dict(host=socket.gethostname(), cwd=str(repo.resolve()),
        branch='provenance', sha=git('rev-parse', '--short', 'HEAD'), tool='provenance-test')
    key = 'PROV168-' + str(created['number'])
    refs = 'gh#42 linear:ENG-118'
    request(prefix + '/' + created['id'], {'refs': refs}, 'PATCH')
    for invalid in ['not an object', [], {'host': 42}]:
        try:
            request(prefix + '/' + created['id'], {'origin': invalid}, 'PATCH')
            raise AssertionError('malformed origin was accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 400
            assert 'origin' in json.load(error)['data']
        assert request(prefix + '/' + created['id'])['origin'] == created['origin']
    for mode in [[], ['--raw']]:
        output = cli('issue', 'view', key, *mode)
        for value in [member['name'], str(repo.resolve()), 'provenance-test', refs]:
            assert value in output, (mode, value)
    # Leaving Git must still allow filing; unavailable coordinates stay empty.
    plain = json.loads(cli('issue', 'create', 'Outside Git', '--json', cwd=base))
    assert plain['origin']['branch'] == '' and plain['origin']['sha'] == ''
    assert plain['origin']['cwd'] == str(base.resolve())
    # Direct member API writes cannot falsely attribute the initial creator.
    other = request('/api/collections/members/records', {'name': 'provenance-other',
        'email': 'provenance-other@example.test', 'password': 'fixture-password',
        'passwordConfirm': 'fixture-password'})
    direct = request(prefix, {'team': team['id'], 'title': 'Direct API', 'state': 'todo', 'creator': other['id']})
    assert direct['creator'] == subject
    # Board writes use the configured actor and leave client Git/host unknown.
    req = urllib.request.Request(board + '/create',
        data=urllib.parse.urlencode({'team': 'PROV168', 'title': 'Browser context'}).encode(),
        headers={'Cookie': 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN']})
    with urllib.request.urlopen(req, timeout=15) as response:
        assert 'ni_open' in response.read().decode(), 'board create failed'
    query = urllib.parse.urlencode({'filter': 'team="' + team['id'] + '" && title="Browser context"'})
    web_issue = request(prefix + '?' + query)['items'][0]
    assert web_issue['creator'] == subject
    assert web_issue['origin']['tool'] == 'web'
    assert all(web_issue['origin'][key] == '' for key in ['host', 'cwd', 'branch', 'sha'])
    req = urllib.request.Request(board + '/issue/' + key,
        headers={'Cookie': 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN']})
    with urllib.request.urlopen(req, timeout=15) as response:
        page = html.unescape(response.read().decode())
    for value in [member['name'], str(repo.resolve()), 'provenance-test', refs]:
        assert value in page, value
    mirror = base / 'mirror'
    result = subprocess.run([binary, 'export', str(mirror)], cwd=base,
        env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert refs in (mirror / 'issues' / (key + '.md')).read_text()
    if shutil.which('playwright-cli'):
        session = new_session()
        try:
            open_session(session, board + '/?board_token=' + os.environ['LLL_TEST_BOARD_TOKEN'])
            script = '''async page => {
              await page.goto(ISSUE_URL);
              await page.getByText(ORIGIN_PATH, {exact: true}).waitFor();
              await page.getByText(REFS, {exact: true}).waitFor();
              for (const width of [1280, 390]) {
                await page.setViewportSize({width, height: 1000});
                await page.screenshot({path: `/tmp/lll-168-provenance-${width}.png`, fullPage: true});
                if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('provenance overflows page');
                if (await page.locator('.provenance-value').evaluateAll(values => values.some(value => value.scrollWidth > value.clientWidth))) throw new Error('provenance text is clipped');
              }
              return 'Provenance browser passed';
            }'''.replace('ISSUE_URL', json.dumps(board + '/issue/' + key)).replace('ORIGIN_PATH', json.dumps(str(repo.resolve()))).replace('REFS', json.dumps(refs))
            result = subprocess.run(['playwright-cli', '-s=' + session, 'run-code', script],
                capture_output=True, text=True, timeout=45)
            require_result(result, 'Provenance browser passed', board)
        finally:
            subprocess.run(['playwright-cli', '-s=' + session, 'close'], capture_output=True, timeout=15)
print('Provenance: CLI Git/plain-directory context, authenticated API creator, browser unknown coordinates, views and export passed')
