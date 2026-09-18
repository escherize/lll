#!/usr/bin/env python3
"""Exercise actual CLI search team overrides, cache separation and config preservation."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import urllib.request
from board_startup import wait_for_endpoints

binary = str(Path(sys.argv[1]).resolve())

def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

with tempfile.TemporaryDirectory(prefix='lll-search-team-') as directory:
    root = Path(directory)
    serverhome, home, work = root/'serverhome', root/'home', root/'work'
    for path in (serverhome, home, work): path.mkdir()
    env = {k:v for k,v in os.environ.items() if not k.startswith(('LLL_', 'XDG_')) and k != 'HOME'}
    env.update(HOME=str(serverhome), LLL_URL=f'http://127.0.0.1:{port()}', LLL_TEAM='ALPHA',
               LLL_BIND='127.0.0.1', USER='search-controller', LLL_ADMIN_EMAIL='search@example.invalid',
               LLL_ADMIN_PASSWORD='local-search-team-password', LLL_BOARD_TOKEN='local-search-team-board')
    log = root/'up.log'
    with log.open('w') as output:
        child = subprocess.Popen([binary,'up','--no-open','--port',str(port()),'--pb-dir',str(root/'data')],
                                 cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        endpoint=wait_for_endpoints(log)
        assert child.poll() is None
        api=endpoint['db_url']
        def request(path, body=None, token=''):
            req=urllib.request.Request(api+path, data=None if body is None else json.dumps(body).encode(),
                                       headers={'Content-Type':'application/json', **({'Authorization':'Bearer '+token} if token else {})})
            with urllib.request.urlopen(req,timeout=15) as response: return json.load(response)
        admin=request('/api/collections/_superusers/auth-with-password',{'identity':env['LLL_ADMIN_EMAIL'],'password':env['LLL_ADMIN_PASSWORD']})['token']
        person=next(m for m in request('/api/collections/members/records',token=admin)['items'] if m['name']=='search-controller')
        token=request('/api/collections/members/impersonate/'+person['id'],{'duration':3600},admin)['token']
        alpha=next(t for t in request('/api/collections/teams/records',token=token)['items'] if t['key']=='ALPHA')
        beta=request('/api/collections/teams/records',{'key':'BETA','name':'Beta'},token)
        for team in (alpha,beta):
            request('/api/collections/issues/records',{'team':team['id'],'title':team['key']+' scope needle',
                    'description':'scope needle --team literal','state':'todo','priority':2},token)
        config=work/'.lll.toml'
        config.write_text(f'url = "{api}"\nteam = "ALPHA"\n')
        machine=home/'.config/lll/lll.toml'
        machine.parent.mkdir(parents=True)
        machine.write_text(f'url = "{api}"\nteam = "ALPHA"\ntoken = "{token}"\n')
        before=(config.read_bytes(),machine.read_bytes())
        base={k:v for k,v in env.items() if not k.startswith(('LLL_', 'XDG_'))}
        base.update(HOME=str(home), LLL_URL=api, LLL_TOKEN=token, LC_ALL='C')
        def run(args,team=None):
            current=dict(base)
            if team: current['LLL_TEAM']=team
            result=subprocess.run([binary,*args],cwd=work,env=current,text=True,capture_output=True,timeout=20)
            assert (config.read_bytes(),machine.read_bytes())==before,'search rewrote config'
            return result
        def hits(args,expected,team=None):
            result=run(['search','--json',*args],team)
            assert result.returncode==0,result.stderr
            data=json.loads(result.stdout)
            assert len(data)==1 and data[0]['group']==expected,(args,data)
        hits(['scope needle'],'ALPHA-1')
        hits(['scope needle'],'BETA-1',team='BETA')
        hits(['scope needle','--team','BETA'],'BETA-1',team='ALPHA')
        hits(['--team=ALPHA','scope needle'],'ALPHA-1',team='BETA')
        hits(['scope needle --team literal','--team=BETA','--refresh'],'BETA-1')
        hits(['scope needle','--team','ALPHA'],'ALPHA-1')
        help_result=run(['search','--help'])
        assert help_result.returncode==0 and '--team' in help_result.stdout
        invalid=run(['search','scope needle','--limit','--team'])
        assert invalid.returncode!=0 and '--limit takes a number' in invalid.stderr and "'--team'" in invalid.stderr,invalid.stderr
        missing=run(['search','scope needle','--team'])
        assert missing.returncode!=0 and '--team requires a team key' in missing.stderr,missing.stderr
        # Query after the option terminator remains text, not a team selector.
        hits(['--team','BETA','--','--team'],'BETA-1')
    finally:
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)
        else: child.wait()
print('Search team: config/environment/explicit scope, both override forms, cache separation, JSON/help, literal query/option values and config preservation passed')
