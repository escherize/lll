#!/usr/bin/env python3
"""HEAD login links preserve GET authentication, scope and CSRF semantics."""
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


with tempfile.TemporaryDirectory(prefix='lll-head-') as directory:
    root = Path(directory)
    (root / 'home').mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root / 'home'), LLL_URL=f'http://127.0.0.1:{port()}',
               LLL_TEAM='HEAD', LLL_BIND='127.0.0.1', USER='head-owner',
               LLL_ADMIN_EMAIL='head@example.invalid', LLL_ADMIN_PASSWORD='local-head-password',
               LLL_BOARD_TOKEN='local-head-board')
    log = root / 'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary, 'up', '--no-open', '--port', str(port()),
                                  '--pb-dir', str(root / 'data')], cwd=root, env=env,
                                 stdout=output, stderr=subprocess.STDOUT)
    try:
        endpoints = wait_for_endpoints(log)
        api, board = endpoints['db_url'], endpoints['board_url']

        def api_call(path, body=None, token=''):
            request = urllib.request.Request(api + path,
                data=None if body is None else json.dumps(body).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)

        su = api_call('/api/collections/_superusers/auth-with-password',
                      {'identity': env['LLL_ADMIN_EMAIL'], 'password': env['LLL_ADMIN_PASSWORD']})['token']
        team = next(t for t in api_call('/api/collections/teams/records', token=su)['items']
                    if t['key'] == 'HEAD')
        api_call('/api/collections/teams/records', {'key': 'HIDDEN', 'name': 'Other team'}, su)
        member = api_call('/api/collections/members/records', {
            'name': 'head-reader', 'email': 'head-reader@example.invalid',
            'password': 'head-reader-password', 'passwordConfirm': 'head-reader-password',
            'scope': 'teams', 'teams': [team['id']], 'access_mode': 'read-only'}, su)
        member_token = api_call('/api/collections/members/impersonate/' + member['id'],
                                {'duration': 3600}, su)['token']
        scoped = 'HEAD.' + hmac.new(env['LLL_BOARD_TOKEN'].encode(), b'HEAD', hashlib.sha256).hexdigest()

        def request(method, path, token='', cookie='', fetch='none', origin=''):
            target = urllib.parse.urlsplit(board)
            connection = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
            headers = {}
            if fetch is not None:
                headers['Sec-Fetch-Site'] = fetch
            if cookie:
                headers['Cookie'] = 'lll_board=' + cookie
            if origin:
                headers['Origin'] = origin
            if token:
                path += ('&' if '?' in path else '?') + urllib.parse.urlencode({'board_token': token})
            try:
                connection.request(method, path, headers=headers)
                response = connection.getresponse()
                status, location = response.status, response.getheader('Location')
                has_cookie = bool(response.getheader('Set-Cookie'))
                body = response.read()
                if method == 'HEAD':
                    assert not body, 'HEAD returned a response body'
                return status, location, has_cookie
            finally:
                connection.close()

        for name, token in [('full', env['LLL_BOARD_TOKEN']), ('team', scoped), ('member', member_token)]:
            for method in ['GET', 'HEAD']:
                actual = request(method, '/t/HEAD/', token=token)
                assert actual == (303, '/t/HEAD/', True), (name, method, actual)
        for token in [scoped, member_token]:
            for fetch in [None, 'same-site', 'cross-site']:
                for method in ['GET', 'HEAD']:
                    actual = request(method, '/t/HEAD/', token=token, fetch=fetch)
                    assert actual == (200, None, False), ('confirmation', method, fetch, actual)
            # A different valid login link never replaces an existing member cookie.
            actual = request('HEAD', '/t/HEAD/', token=token, cookie=member_token)
            assert actual == (303, '/t/HEAD/', token == member_token), ('existing login', actual)
            for method in ['GET', 'HEAD']:
                assert request(method, '/t/HEAD/', cookie=token)[0] == 200
                assert request(method, '/t/HIDDEN/', cookie=token)[0] == 404
                assert request(method, '/', cookie=token)[:2] == (303, '/t/HEAD/')
            assert request('HEAD', '/events', cookie=token)[0] == 403
            assert request('POST', '/state', cookie=token, origin=board)[0] == 403
            assert request('POST', '/state', cookie=token, origin='https://foreign.invalid')[0] == 403
        assert request('HEAD', '/t/HEAD/', token='invalid')[0] == 401
        print('HEAD board links: login, confirmation, cookies, hidden teams, bodyless reads and write/stream refusal passed')
    finally:
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
