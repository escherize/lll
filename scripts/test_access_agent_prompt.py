"""Exercise the show-once Access prompt on an owned, split-origin board."""
import html
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import uuid
import urllib.request
from pathlib import Path
from board_startup import wait_for_endpoints, wait_for_board

binary = str(Path(sys.argv[1]).resolve())
bind = sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1'
if bind == 'lan':
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect(('192.0.2.1', 9))  # route selection only; sends no packet
        bind = route.getsockname()[0]
    assert not bind.startswith('127.'), 'LAN fixture needs a non-loopback interface'
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

with tempfile.TemporaryDirectory(prefix='lll-507-') as directory:
    root = Path(directory)
    (root/'home').mkdir()
    env = {k:v for k,v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(root/'home'), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='BOOT',
               LLL_BIND=bind, USER='prompt-owner', LLL_ADMIN_EMAIL='prompt@example.invalid',
               LLL_ADMIN_PASSWORD='local-prompt-password', LLL_BOARD_TOKEN='local-prompt-board')
    log = root/'up.log'
    web_port = port()
    with log.open('w') as output:
        child = subprocess.Popen([binary,'up','--no-open','--pb-dir',str(root/'data'),'--port',str(web_port),'--bind',bind],
                                 cwd=root,env=env,stdout=output,stderr=subprocess.STDOUT)
    try:
        if bind == '127.0.0.1':
            endpoints = wait_for_endpoints(log)
            api, board = endpoints['db_url'], endpoints['board_url']
        else:
            wait_for_board(log, f'http://{bind}:{web_port}')
            announced = re.search(r'^api    (http://[^ ]+)$', log.read_text(), re.M)
            assert announced and urllib.parse.urlsplit(announced[1]).hostname in ('127.0.0.1',bind), 'owned API did not announce a local endpoint'
            api, board = announced[1], f'http://{bind}:{web_port}'
        def call(base,path,body=None,token='',headers=None,method=None):
            hdr = dict(headers or {})
            if token: hdr['Authorization'] = 'Bearer '+token
            if body is not None: hdr['Content-Type'] = 'application/json'
            request = urllib.request.Request(base+path,headers=hdr,data=None if body is None else json.dumps(body).encode(),method=method)
            with http.open(request,timeout=15) as response: return json.load(response)
        su = call(api,'/api/collections/_superusers/auth-with-password',
                  {'identity':env['LLL_ADMIN_EMAIL'],'password':env['LLL_ADMIN_PASSWORD']})['token']
        other = call(api,'/api/collections/teams/records',{'key':'OTHER_TEAM','name':'Other team'},su)
        name = '<script>window.injected=true</script> & O\'Brien'
        member = call(api,'/api/collections/members/records',
                      {'name':name,'kind':'person','email':'agent@example.invalid','password':'local-agent-password',
                       'passwordConfirm':'local-agent-password','scope':'all','mode':'rw'},su)
        def page(path,body=None,headers=None):
            hdr = {'Cookie':'lll_board='+env['LLL_BOARD_TOKEN'], **(headers or {})}
            if body is not None:
                hdr['Content-Type']='application/x-www-form-urlencoded'
                hdr['Origin'] = (hdr.get('X-Forwarded-Proto','http')+'://'+hdr['Host']) if 'Host' in hdr else board
            request = urllib.request.Request(board+path,headers=hdr,data=None if body is None else body.encode())
            try:
                with http.open(request,timeout=15) as response:return response.status,response.read().decode(),response.headers
            except urllib.error.HTTPError as error:return error.code,error.read().decode(),error.headers
        # The actual page must carry its own team into the write.
        code, body, _ = page('/t/OTHER_TEAM/settings/access')
        assert code == 200 and '/t/OTHER_TEAM/settings/access/token' in body, 'mint form does not name its viewed team'
        form = urllib.parse.urlencode({'member':member['id'],'admin_password':env['LLL_ADMIN_PASSWORD']})
        cases = [(None,board)]
        if bind != '127.0.0.1':
            cases += [({'Host':'192.0.2.17:8765'},'http://192.0.2.17:8765'),
                      ({'Host':'board.example.test','X-Forwarded-Proto':'https'},'https://board.example.test')]
        seen = []
        for headers, origin in cases:
            code, body, response_headers = page('/t/OTHER_TEAM/settings/access/token',form,headers)
            assert code == 200, (origin, code, body[:250])
            match = re.search(r'<pre[^>]*id="access-agent-prompt"[^>]*>(.*?)</pre>',body,re.S)
            assert match, 'mint did not render its complete agent prompt'
            prompt = html.unescape(match.group(1))
            token = re.search(r'export LLL_TOKEN=([^\s]+)',prompt).group(1)
            seen.append(token)
            assert f'export LLL_URL={origin}\n' in prompt, 'prompt used the API listener/default instead of browser origin'
            assert 'export LLL_TEAM=OTHER_TEAM\n' in prompt and 'export LLL_TEAM=BOOT' not in prompt
            assert 'lll skill get software-factory' in prompt and 'Claim an issue before' in prompt
            assert origin+'/t/OTHER_TEAM/' in prompt
            assert 'token = ' not in prompt and '.lll.toml' not in prompt
            assert '<script>' not in body and '&lt;script&gt;' in body, 'member name escaped incorrectly'
            assert response_headers.get('Cache-Control') == 'no-store'
            assert call(api,'/api/collections/members/auth-refresh',{},token)['record']['id'] == member['id']
        _, bare, _ = page('/settings/access/token',form)
        assert 'this settings form names no team' in bare and 'id="access-agent-prompt"' not in bare
        # LLL-742: authenticate is not enough; the advertised team must be readable.
        def make_member(name, **fields):
            body = {'name':name,'kind':'person','scope':'all','mode':'rw',
                    'email':name+'@example.invalid','password':'local-scope-password',
                    'passwordConfirm':'local-scope-password', **fields}
            return call(api,'/api/collections/members/records',body,su)
        def mint_for(record):
            return page('/t/OTHER_TEAM/settings/access/token',urllib.parse.urlencode(
                {'member':record['id'],'admin_password':env['LLL_ADMIN_PASSWORD']}))[1]
        visible = make_member('visible-member',scope='teams',teams=[other['id']])
        visible_out = mint_for(visible)
        visible_prompt = re.search(r'<pre[^>]*id="access-agent-prompt"[^>]*>(.*?)</pre>',visible_out,re.S)
        assert visible_prompt, 'visible scoped member was incorrectly refused'
        visible_token = re.search(r'export LLL_TOKEN=([^\s]+)',html.unescape(visible_prompt.group(1))).group(1)
        assert [t['id'] for t in call(api,'/api/collections/teams/records',token=visible_token)['items']] == [other['id']]
        unseen = make_member('unseen-member',scope='teams',teams=[])
        owner = make_member('scope-owner')
        bot = make_member('bot-scope-check',kind='bot',owner=owner['id'])
        call(api,'/api/collections/members/records/'+owner['id'],{'scope':'teams','teams':[]},su,method='PATCH')
        for incompatible in (unseen,bot):
            before = call(api,'/api/collections/members/records/'+incompatible['id'],token=su)
            refused_scope = mint_for(incompatible)
            assert 'cannot see team OTHER_TEAM' in refused_scope, 'inaccessible selection received no scope recovery'
            assert 'access-agent-prompt' not in refused_scope and 'access-token-value' not in refused_scope, 'unusable token/prompt was shown'
            after = call(api,'/api/collections/members/records/'+incompatible['id'],token=su)
            for field in ('scope','teams','mode','owner'):
                assert after.get(field) == before.get(field), 'mint widened or changed member access'
        code, reloaded, _ = page('/t/OTHER_TEAM/settings/access')
        assert code == 200 and 'id="access-agent-prompt"' not in reloaded
        assert all(token not in reloaded for token in seen), 'page reload redisclosed a token'
        code, refused, _ = page('/t/OTHER_TEAM/settings/access/token',urllib.parse.urlencode({'member':member['id']}))
        assert 'admin password is required' in refused and 'id="access-agent-prompt"' not in refused
        if bind == '127.0.0.1':
            from browser_session import require_result
            browser_env = dict(env, PLAYWRIGHT_MCP_CONFIG=str(Path(__file__).resolve().parent/'browser-ci.json'))
            session = uuid.uuid4().hex[:14]
            def browser(*args):
                result = subprocess.run(['playwright-cli','-s='+session,*args], env=browser_env,
                                        cwd=root,capture_output=True,text=True,timeout=90)
                assert result.returncode == 0 and '### Error' not in result.stdout+result.stderr, 'owned browser command failed'
                return result
            try:
                browser('open',board+'/?board_token='+env['LLL_BOARD_TOKEN'])
                source = r"""async page => {
                  await page.goto(__PAGE__);
                  const form = page.locator('#access-token-form');
                  await form.locator('select[name=member]').selectOption(__MEMBER__);
                  await form.locator('input[name=admin_password]').fill(__PASSWORD__);
                  await form.getByRole('button', {name:'Mint token',exact:true}).click();
                  const prompt = page.locator('#access-agent-prompt');
                  await prompt.waitFor();
                  if (await page.evaluate(() => Boolean(window.injected))) throw new Error('member name executed');
                  await page.context().grantPermissions(['clipboard-read','clipboard-write'], {origin:__ORIGIN__});
                  const button = page.locator('[data-copy-from=access-agent-prompt]');
                  await button.click();
                  await page.waitForFunction(() => document.querySelector('[data-copy-from=access-agent-prompt]').textContent === 'Copied');
                  if (!await page.evaluate(async () => await navigator.clipboard.readText() === document.getElementById('access-agent-prompt').textContent)) throw new Error('dynamic prompt copy differs');
                  await page.waitForFunction(() => document.querySelector('[data-copy-from=access-agent-prompt]').textContent === 'Copy agent prompt');
                  await page.evaluate(() => { navigator.clipboard.writeText = async () => { throw new Error('simulate plain HTTP'); }; });
                  await button.click();
                  await page.waitForFunction(() => document.querySelector('[data-copy-from=access-agent-prompt]').textContent === 'Copied');
                  if (!await page.evaluate(async () => await navigator.clipboard.readText() === document.getElementById('access-agent-prompt').textContent)) throw new Error('LAN fallback copy differs');
                  await page.waitForFunction(() => document.querySelector('[data-copy-from=access-agent-prompt]').textContent === 'Copy agent prompt');
                  await page.evaluate(() => { document.execCommand = () => false; });
                  await button.click();
                  await page.waitForFunction(() => document.querySelector('[data-copy-from=access-agent-prompt]').textContent === 'Copy failed');
                  await page.evaluate(() => {
                    for (const el of document.querySelectorAll('#access-token-result code, #access-agent-prompt')) el.textContent = el.textContent.replace(/eyJ[A-Za-z0-9_.-]+/g,'[fixture-token-redacted]');
                  });
                  await page.screenshot({path:'/tmp/lll-507-access-desktop.png',fullPage:true});
                  await page.setViewportSize({width:390,height:844});
                  await page.screenshot({path:'/tmp/lll-507-access-mobile.png',fullPage:true});
                  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('prompt overflows narrow screen');
                  await page.reload();
                  if (await page.locator('#access-agent-prompt').count()) throw new Error('reload redisclosed prompt');
                  return 'Access prompt browser: dynamic copy, LAN fallback, failure feedback, escaping, responsive layout and reload passed';
                }"""
                for key,value in {'__PAGE__':board+'/t/OTHER_TEAM/settings/access','__MEMBER__':member['id'],
                                  '__PASSWORD__':env['LLL_ADMIN_PASSWORD'],'__ORIGIN__':board}.items():
                    source = source.replace(key,json.dumps(value))
                result = browser('run-code',source)
                require_result(result,'Access prompt browser: dynamic copy, LAN fallback, failure feedback, escaping, responsive layout and reload passed',board)
            finally:
                subprocess.run(['playwright-cli','-s='+session,'close'],env=browser_env,cwd=root,
                               capture_output=True,text=True,timeout=30)
        print(f'Access agent prompt ({bind}): routed team, observed origins, real token identity, escaping, no-store and show-once passed')
    finally:
        child.terminate()
        try:child.wait(timeout=20)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
