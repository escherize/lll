"""Exercise the show-once Access prompt on an owned, split-origin board."""
import html
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())
def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

with tempfile.TemporaryDirectory(prefix='lll-507-') as directory:
    root = Path(directory)
    (root/'home').mkdir()
    env = {k:v for k,v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root/'home'), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='BOOT',
               LLL_BIND='127.0.0.1', USER='prompt-owner', LLL_ADMIN_EMAIL='prompt@example.invalid',
               LLL_ADMIN_PASSWORD='local-prompt-password', LLL_BOARD_TOKEN='local-prompt-board')
    log = root/'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary,'up','--no-open','--pb-dir',str(root/'data'),'--port',str(port())],
                                 cwd=root,env=env,stdout=output,stderr=subprocess.STDOUT)
    try:
        endpoints = wait_for_endpoints(log)
        api, board = endpoints['db_url'], endpoints['board_url']
        def call(base,path,body=None,token='',headers=None):
            hdr = dict(headers or {})
            if token: hdr['Authorization'] = 'Bearer '+token
            if body is not None: hdr['Content-Type'] = 'application/json'
            request = urllib.request.Request(base+path,headers=hdr,data=None if body is None else json.dumps(body).encode())
            with urllib.request.urlopen(request,timeout=15) as response: return json.load(response)
        su = call(api,'/api/collections/_superusers/auth-with-password',
                  {'identity':env['LLL_ADMIN_EMAIL'],'password':env['LLL_ADMIN_PASSWORD']})['token']
        call(api,'/api/collections/teams/records',{'key':'OTHER','name':'Other team'},su)
        name = '<script>window.injected=true</script> & O\'Brien'
        member = call(api,'/api/collections/members/records',
                      {'name':name,'kind':'person','email':'agent@example.invalid','password':'local-agent-password',
                       'passwordConfirm':'local-agent-password','scope':'all','mode':'rw'},su)
        def page(path,body=None,headers=None):
            hdr = {'Cookie':'lll_board='+env['LLL_BOARD_TOKEN'], **(headers or {})}
            if body is not None: hdr['Content-Type']='application/x-www-form-urlencoded'
            request = urllib.request.Request(board+path,headers=hdr,data=None if body is None else body.encode())
            try:
                with urllib.request.urlopen(request,timeout=15) as response:return response.status,response.read().decode(),response.headers
            except urllib.error.HTTPError as error:return error.code,error.read().decode(),error.headers
        # The actual page must carry its own team into the write.
        code, body, _ = page('/t/OTHER/settings/access')
        assert code == 200 and '/t/OTHER/settings/access/token' in body, 'mint form does not name its viewed team'
        form = urllib.parse.urlencode({'member':member['id'],'admin_password':env['LLL_ADMIN_PASSWORD']})
        cases = [(None,board), ({'Host':'192.0.2.17:8765'},'http://192.0.2.17:8765'),
                 ({'Host':'board.example.test','X-Forwarded-Proto':'https'},'https://board.example.test')]
        seen = []
        for headers, origin in cases:
            code, body, response_headers = page('/t/OTHER/settings/access/token',form,headers)
            assert code == 200, code
            match = re.search(r'<pre[^>]*id="access-agent-prompt"[^>]*>(.*?)</pre>',body,re.S)
            assert match, 'mint did not render its complete agent prompt'
            prompt = html.unescape(match.group(1))
            token = re.search(r'export LLL_TOKEN=([^\s]+)',prompt).group(1)
            seen.append(token)
            assert f'export LLL_URL={origin}\n' in prompt, 'prompt used the API listener/default instead of browser origin'
            assert 'export LLL_TEAM=OTHER\n' in prompt and 'export LLL_TEAM=BOOT' not in prompt
            assert 'lll skill get software-factory' in prompt and 'Claim an issue before' in prompt
            assert origin+'/t/OTHER/' in prompt
            assert 'token = ' not in prompt and '.lll.toml' not in prompt
            assert '<script>' not in body and '&lt;script&gt;' in body, 'member name escaped incorrectly'
            assert response_headers.get('Cache-Control') == 'no-store'
            assert call(api,'/api/collections/members/auth-refresh',{},token)['record']['id'] == member['id']
        code, reloaded, _ = page('/t/OTHER/settings/access')
        assert code == 200 and 'id="access-agent-prompt"' not in reloaded
        assert all(token not in reloaded for token in seen), 'page reload redisclosed a token'
        code, refused, _ = page('/t/OTHER/settings/access/token',urllib.parse.urlencode({'member':member['id']}))
        assert 'admin password is required' in refused and 'id="access-agent-prompt"' not in refused
        print('Access agent prompt: routed team, local/LAN/proxy origins, real token identity, escaping, no-store and show-once passed')
    finally:
        child.terminate()
        try:child.wait(timeout=20)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
