#!/usr/bin/env python3
"""Real CLI and board attachment lifecycle on an isolated e2e service."""
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from browser_session import new_session, open_session
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

binary, api, board = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='ATT35')
cookie = 'lll_board=' + os.environ['LLL_TEST_BOARD_TOKEN']


def cli(*args, success=True, cwd=None):
    result = subprocess.run([binary, *args], env=env, text=True, capture_output=True, timeout=30, cwd=cwd)
    assert (result.returncode == 0) == success, result.stderr
    return result.stdout if success else result.stderr


def request(url, data=None, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers or {}), timeout=30) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


cli('team', 'create', '-k', 'ATT35', '-n', 'Attachment verification')
issue = json.loads(cli('issue', 'create', 'Attachment lifecycle', '--description', 'Preserve description', '--json'))
key = f"ATT35-{issue['number']}"


def view():
    return json.loads(cli('issue', 'view', key, '--json'))


def stable(record):
    return {k: v for k, v in record.items() if k not in ['attachments', 'updated']}


cli('issue', 'claim', key)
cli('issue', 'comment', key, '-b', 'Preserve claim and comment')
before = view()
# A real-sized raster fixture, generated without image/library dependencies.
def chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
width, height = 320, 120
pixels = b''.join(b'\0' + bytes([40, 90 + row, 130]) * width for row in range(height))
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')
with tempfile.TemporaryDirectory(prefix='lll-35-files-') as directory:
    root = Path(directory)
    image = root / 'shot.png'; image.write_bytes(png)
    report = root / '-report with spaces.html'; report.write_text('<script>window.attachmentExecuted=true</script><h1>Report</h1>')
    cli('issue', 'attach', board + '/issue/' + key + '?source=test#files', str(image))
    cli('issue', 'attach', key, '--', report.name, cwd=root)
    saved = view()
    assert len(saved['attachments']) == 2
    assert stable(saved) == stable(before)
    for name in saved['attachments']:
        assert name in cli('issue', 'view', key)
        assert name in cli('issue', 'view', key, '--raw')
        fetched = subprocess.run([binary, 'issue', 'download', board + '/issue/' + key, name], env=env, capture_output=True, timeout=30)
        expected = png if name.endswith('.png') else report.read_bytes()
        assert fetched.returncode == 0 and fetched.stdout == expected, 'CLI download changed bytes'
        direct = f'{api}/api/files/issues/{issue["id"]}/{urllib.parse.quote(name)}'
        assert request(direct)[0] == 404, 'native file is public'
        assert request(direct, headers={'Authorization': 'Bearer ' + env['LLL_TOKEN']})[0] == 404
        url = board + '/attachments/file?' + urllib.parse.urlencode(dict(key=key, file=name))
        assert request(url)[0] == 401, 'board download bypassed its gate'
        status, headers, data = request(url, headers={'Cookie': cookie})
        assert status == 200, (status, data[:200])
        assert headers['Cache-Control'] == 'private, no-store'
        assert headers['X-Content-Type-Options'] == 'nosniff'
        assert headers['Content-Security-Policy'] == 'sandbox'
        if name.endswith('.png'):
            assert data == png and headers['Content-Disposition'].startswith('inline;')
            _, headers, _ = request(url + '&download=1', headers={'Cookie': cookie})
            assert headers['Content-Disposition'].startswith('attachment;')
            status, _, piece = request(url, headers={'Cookie': cookie, 'Range': 'bytes=0-7'})
            assert status == 206 and piece == png[:8]
        else:
            assert data == report.read_bytes()
            assert headers['Content-Disposition'].startswith('attachment;'), 'HTML must download'
    bad_url = board + '/attachments/file?' + urllib.parse.urlencode(dict(key=key, file='../not-a-file'))
    assert request(bad_url, headers={'Cookie': cookie})[0] == 404
    # Native append semantics must retain independent concurrent uploads.
    files = []
    for n in range(4):
        path = root / f'parallel-{n}.txt'; path.write_text(f'parallel {n}'); files.append(path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        uploads = list(pool.map(lambda path: cli('issue', 'attach', key, str(path)), files))
    assert all(len(output.splitlines()) == 1 for output in uploads), 'upload reported another concurrent file'
    assert len(set(uploads)) == 4
    assert len(view()['attachments']) == 6, 'concurrent append lost a file'
    oversized = root / 'too-large.bin'
    with oversized.open('wb') as stream:
        stream.truncate(20 * 1024 * 1024 + 1)
    snapshot = view()
    cli('issue', 'attach', key, str(oversized), success=False)
    cli('issue', 'attach', key, str(root / 'missing'), success=False)
    cli('issue', 'detach', key, 'missing.txt', success=False)
    missing = subprocess.run([binary, 'issue', 'download', key, 'missing.txt'], env=env, capture_output=True)
    assert missing.returncode != 0 and missing.stdout == b''
    assert view() == snapshot, 'failed attachment operation changed the issue'
    removed = snapshot['attachments'][0]
    cli('issue', 'detach', key, removed)
    assert removed not in view()['attachments']
    assert stable(view()) == stable(before)
    assert request(board + '/attachments/file?' + urllib.parse.urlencode(dict(key=key, file=removed)), headers={'Cookie': cookie})[0] == 404
    # Keep an image and report for browser inspection. Removing the issue at
    # the end of the suite disposes of all fixture files with its database.
    cli('issue', 'attach', key, str(image))
    limited = json.loads(cli('issue', 'create', 'Attachment count limit', '--json'))
    limit_key = f"ATT35-{limited['number']}"
    for _ in range(20):
        cli('issue', 'attach', limit_key, str(image))
    limit_before = cli('issue', 'view', limit_key, '--json')
    assert len(json.loads(limit_before)['attachments']) == 20
    cli('issue', 'attach', limit_key, str(image), success=False)
    assert cli('issue', 'view', limit_key, '--json') == limit_before
    cli('team', 'archive', 'ATT35')
    snapshot = view()
    cli('issue', 'attach', key, str(image), success=False)
    cli('issue', 'detach', key, snapshot['attachments'][0], success=False)
    assert view() == snapshot
    cli('team', 'unarchive', 'ATT35')

print('Attachments: append/concurrency, protected byte-exact downloads, HTML download, range, removal, failure preservation and archive guards passed')
print('Attachment browser fixture:', key)

# Browser checks use the same database and fixture, with an isolated session.
import shutil
if shutil.which('playwright-cli'):
    session = new_session()
    Path('/tmp/lll-35-browser-upload.txt').write_text('Browser attachment fixture\n')
    try:
        open_session(session, board + '/?board_token=' + os.environ['LLL_TEST_BOARD_TOKEN'])
        result = subprocess.run(['playwright-cli', '-s=' + session, 'run-code', Path('scripts/browser_attachments.js').read_text()], text=True, capture_output=True, timeout=90)
        output = result.stdout + result.stderr
        Path('/tmp/lll-35-browser-gate.log').write_text(output)
        assert '### Error' not in output and 'Attachment browser: upload/remove live' in output, 'attachment browser failed; see /tmp/lll-35-browser-gate.log'
        print('Attachment browser: real upload/removal, rejected retry, live counts, drafts and responsive screenshots passed')
    finally:
        subprocess.run(['playwright-cli', '-s=' + session, 'close'], capture_output=True, timeout=15)
