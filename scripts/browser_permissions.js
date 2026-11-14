// Real permission-management flows, in the board's existing browser driver.
async page => {
  const fixture = __PERMISSION_FIXTURE__;
  const board = fixture.board;
  const root = fixture.capture;
  const must = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const cookie = async value => {
    await page.context().addCookies([{name:'lll_board',value,url:board}]);
  };
  const access = async () => {
    const response = await page.request.get(fixture.api + '/api/lll/access', {headers:{Authorization:'Bearer '+fixture.aliceToken}});
    must(response.ok(),'cannot inspect current Alice grant');
    return response.json();
  };
  const row = key => page.locator('.perm-teams tbody tr').filter({has:page.locator('th strong',{hasText:new RegExp('^'+key+'$')})});
  const open = async member => {
    const response = await page.goto(board+'/permissions?member='+member);
    must(response.ok(),'permissions page did not open');
    await page.evaluate(()=>document.fonts.ready);
  };
  const change = async (key,role,apply=true,convert=false) => {
    const team = row(key);
    await team.locator('summary').click();
    await team.locator('select[name="role"]').selectOption(role);
    if(convert) await team.locator('input[name="convert_all"]').check();
    await team.getByRole('button',{name:'Preview change',exact:true}).click();
    await page.locator('#permission-review-heading').waitFor();
    must(await page.locator('#permission-apply').isVisible(),'review did not bind an apply form');
    if(apply){
      await page.locator('#permission-apply button[type="submit"]').click();
      await page.locator('.perm-message[role="status"]').waitFor();
    }
  };
  const shot = async name => {
    if(root) await page.screenshot({path:root+'/'+name+'.png',fullPage:page.viewportSize().width>700});
  };
  await cookie(fixture.managerToken);
  await page.setViewportSize({width:1440,height:1200});
  await page.goto(board+'/');
  must(new URL(page.url()).pathname==='/permissions','admin without data was stranded at the root');
  await open(fixture.alice);
  must((await row('ENG').locator('td[data-label="Grant"]').innerText())==='Editor' && (await row('ENG').locator('td[data-label="Effective access"] strong').innerText())==='Editor','Engineering grant/effective role missing');
  must((await row('FIN').locator('td[data-label="Grant"]').innerText())==='Viewer' && (await row('FIN').locator('td[data-label="Effective access"] strong').innerText())==='Viewer','Finance grant/effective role missing');
  await shot('desktop-management');
  await page.setViewportSize({width:390,height:844});
  await shot('mobile-management-top');
  await page.locator('.perm-scroll').evaluate(el=>{
    const section=document.getElementById('permission-teams');
    el.scrollTop+=section.getBoundingClientRect().top-el.getBoundingClientRect().top-14;
  });
  await shot('mobile-team-roles');
  must(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth && document.documentElement.scrollHeight<=innerHeight+1),'mobile page overflows its viewport');
  await change('ENG','viewer',false);
  must((await access()).teams.find(t=>t.key==='ENG').role==='editor','preview changed the grant');
  await page.locator('.perm-review').scrollIntoViewIfNeeded();
  await shot('mobile-review');
  const edit = async (team,role) => {
    const headers={Authorization:'Bearer '+fixture.managerToken};
    const current=await page.request.get(fixture.api+'/api/lll/permissions/'+fixture.alice,{headers});
    const state=await current.json();
    const result=await page.request.post(fixture.api+'/api/lll/permissions/'+fixture.alice,{headers,data:{revision:state.revision,team,role}});
    must(result.ok(),'could not prepare a concurrent grant change');
  };
  await edit(fixture.finance,'editor');
  await page.locator('#permission-apply button[type="submit"]').click();
  await page.locator('.perm-error').waitFor();
  must((await page.locator('.perm-error').innerText()).includes('Permissions changed'),'stale preview did not explain recovery');
  must((await access()).teams.find(t=>t.key==='ENG').role==='editor','stale apply changed Engineering');
  await page.locator('.perm-error').scrollIntoViewIfNeeded();
  await shot('mobile-stale-preview');
  await open(fixture.alice);
  await change('ENG','viewer');
  must((await access()).teams.find(t=>t.key==='ENG').role==='viewer','Apply did not change the grant');
  await edit(fixture.finance,'viewer');
  await open(fixture.alice);
  await change('ENG','editor');
  must((await access()).teams.find(t=>t.key==='ENG').role==='editor','restoring Editor failed');
  await open(fixture.bot);
  must((await page.locator('.perm-identity').innerText()).includes('owned by alice'),'bot ownership is not explained');
  await row('ENG').scrollIntoViewIfNeeded();
  await shot('mobile-bot-authority');
  await open(fixture.broad);
  await change('FIN','viewer',false,true);
  must((await page.locator('.perm-review').innerText()).includes('Future-team access will be removed'),'conversion hides future-team loss');
  must((await page.locator('.perm-review').innerText()).includes('legacy all-team management grant'),'conversion hides management loss');
  await page.locator('.perm-review').scrollIntoViewIfNeeded();
  await shot('mobile-legacy-conversion');
  // Data pages use the viewer's role for this team, not a global "can write".
  await cookie(fixture.aliceToken);
  await page.goto(board+'/t/ENG/issue/'+fixture.engKey);
  must(await page.getByRole('button',{name:'Edit description',exact:true}).isVisible(),'Engineering Editor lost editing controls');
  await page.goto(board+'/t/FIN/issue/'+fixture.finKey);
  must(await page.getByRole('button',{name:'Edit description',exact:true}).count()===0,'Finance Viewer received editing controls');
  const denied=await page.goto(board+'/permissions');
  must(denied.status()===403,'ordinary member opened administration');
  await cookie(fixture.boardToken);
  const setup=await page.goto(board+'/permissions');
  must(setup.status()===403,'legacy board identity became Admin implicitly');
  must((await page.locator('body').innerText()).includes('assign the initial Admin'),'initial operator setup is not explained');
  await shot('mobile-admin-required');
  await cookie(fixture.managerToken);
  await open(fixture.alice);
  const raw=await page.request.get(board+'/permissions?member='+fixture.alice+'&raw');
  must(raw.ok() && (await raw.text()).includes('"editor"'),'agent-readable permissions missing');
  await page.setViewportSize({width:1440,height:1200});
  must(!errors.length,'JavaScript errors: '+errors.join(';'));
  return 'permissions mobile, preview/apply, conversion, bot explanation and per-team controls passed';
}
