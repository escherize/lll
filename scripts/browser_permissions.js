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
  const change = async (key,role,apply=true) => {
    const team = row(key);
    await team.locator('summary').click();
    await team.locator('select[name="role"]').selectOption(role);
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
  must((await page.evaluate(()=>location.pathname))==='/permissions','admin without data was stranded at the root');
  // LLL-812: with no member chosen the page is the whole workspace at a
  // glance: one row per member, one column per team.
  const roster = (await page.request.get(fixture.api+'/api/lll/permissions',{headers:{Authorization:'Bearer '+fixture.managerToken}}).then(r=>r.json())).members;
  const grid = page.locator('.perm-overview');
  const member = name => grid.locator('tbody tr').filter({has:page.locator('th a',{hasText:new RegExp('^'+name+'$')})});
  must(await grid.locator('tbody tr').count()===roster.length,'overview does not list every member');
  must(await page.locator('#permission-member').count()===0,'overview still asks for one member at a time');
  const aliceName = roster.find(m=>m.id===fixture.alice).name;
  must((await member(aliceName).locator('td[data-team="ENG"]').innerText()).trim()==='Editor','overview hides the Engineering role');
  must((await member(aliceName).locator('td[data-team="FIN"]').innerText()).trim()==='Viewer','overview hides the Finance role');
  const legacy = roster.filter(m=>m.all).length;
  must(legacy>0 && (await page.locator('.perm-summary').innerText()).includes(legacy+' with an all-team grant'),'overview does not count the remaining all-team grants');
  must(await grid.locator('tbody tr .perm-all').count()===legacy,'overview does not mark each all-team grant');
  must(await grid.locator('tbody tr td[data-label="Workspace"]',{hasText:/^Admin$/}).count()===roster.filter(m=>m.workspace_role==='admin').length,'overview does not show who is Admin');
  const botName = roster.find(m=>m.id===fixture.bot).name;
  must((await member(botName).locator('th').innerText()).includes('bot'),'overview does not mark bots');
  await shot('desktop-overview');
  await page.locator('.perm-filter input[name="q"]').fill(aliceName.slice(0,3));
  await page.locator('.perm-filter button[type="submit"]').click();
  await grid.waitFor();
  const shown = await grid.locator('tbody tr th a').allInnerTexts();
  must(shown.length>0 && shown.length<roster.length && shown.every(n=>n.toLowerCase().includes(aliceName.slice(0,3).toLowerCase())),'filter did not narrow the members: '+shown.join(','));
  await page.setViewportSize({width:390,height:844});
  await page.goto(board+'/permissions');
  must(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overview makes the phone page scroll sideways');
  await shot('mobile-overview');
  await page.setViewportSize({width:1440,height:1200});
  await member(aliceName).locator('th a').click();
  await page.locator('.perm-identity').waitFor();
  must((await page.locator('.perm-identity h2').innerText())===aliceName,'a row did not open its member');
  await page.locator('.crumbs a[href="/permissions"]').click();
  await grid.waitFor();
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
  // LLL-811: a stale apply names whose permissions moved, in plain words,
  // and leaves the team being edited open on the reloaded page.
  must((await page.locator('.perm-error').innerText()).includes('changed since this page loaded'),'stale preview did not explain recovery');
  must(await row('ENG').locator('details').evaluate(el=>el.open),'stale apply closed the team being edited');
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
  // LLL-810: a role change on an all-team member IS a conversion. The first
  // attempt reaches the preview; no checkbox stands in the way.
  must(await page.locator('.perm-teams input[type="checkbox"]').count()===0,'conversion still hides behind a checkbox');
  const teamCount = await page.locator('.perm-teams tbody tr').count();
  await change('FIN','viewer',false);
  const conversion = await page.locator('.perm-review').innerText();
  must((await page.locator('#permission-review-heading').innerText()).startsWith('Convert '),'conversion preview is not named as one');
  must(conversion.includes('Future-team access will be removed'),'conversion hides future-team loss');
  must(conversion.includes('legacy all-team management grant'),'conversion hides management loss');
  must(conversion.includes('cannot restore'),'conversion does not say it is one-way here');
  must(!conversion.includes('convert_all') && await page.locator('.perm-error').count()===0,'conversion preview leaks an API name or errors');
  must(await page.locator('.perm-review .perm-diff > div').count()===teamCount,'conversion preview does not list every resulting team role');
  must((await page.locator('#permission-apply button[type="submit"]').innerText())==='Convert and apply','apply button does not name the conversion');
  must((await page.request.get(fixture.api+'/api/lll/permissions/'+fixture.broad,{headers:{Authorization:'Bearer '+fixture.managerToken}}).then(r=>r.json())).all===true,'previewing a conversion applied it');
  await page.locator('.perm-review').scrollIntoViewIfNeeded();
  await shot('mobile-legacy-conversion');
  // Data pages use the viewer's role for this team, not a global "can write".
  await cookie(fixture.aliceToken);
  await page.goto(board+'/t/ENG/issue/'+fixture.engKey);
  must(await page.getByRole('button',{name:'Edit description',exact:true}).isVisible(),'Engineering Editor lost editing controls');
  await page.goto(board+'/t/FIN/issue/'+fixture.finKey);
  must(await page.getByRole('button',{name:'Edit description',exact:true}).count()===0,'Finance Viewer received editing controls');
  must(await page.getByRole('button',{name:'Edit issue title',exact:true}).count()===0,'Viewer received title editing');
  must(await page.locator('#state-form select').isDisabled(),'Viewer received an enabled state control');
  must(await page.locator('#comment-form,#attachment-upload').count()===0,'Viewer received a write form');
  must((await page.locator('#issue-detail').innerText()).includes('Read-only for this login.'),'Viewer role was not explained');
  must(await page.locator('#labels-form input[type="checkbox"]:checked').isDisabled(),'Viewer could remove a label');
  must(await page.locator('#labels-form .chip').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize)>=11),'Viewer label name is below the functional text floor');
  await shot('mobile-viewer-issue');
  await page.setViewportSize({width:1440,height:1200});
  await shot('desktop-viewer-issue');
  await page.setViewportSize({width:390,height:844});
  await page.goto(board+'/t/ENG/issue/'+fixture.engKey);
  must(await page.locator('#state-form select').isEnabled(),'Editor lost state editing');
  must(await page.locator('#comment-form').count()===1,'Editor lost commenting');
  must(await page.locator('#labels-form .chip').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize)>=11),'Editor label name is below the functional text floor');
  await shot('mobile-editor-issue');
  await page.setViewportSize({width:1440,height:1200});
  await shot('desktop-editor-issue');
  await page.setViewportSize({width:390,height:844});

  // LLL-811: every non-admin gets the same refusal inside the board, with a
  // way back and a way to sign in as someone else.
  const refusal = async who => {
    must(await page.locator('.perm-app .perm-refusal').isVisible(),who+' refusal is not the styled page');
    must(await page.locator('.perm-refusal a[href="/"]').isVisible(),who+' refusal has no way back to the board');
    must(await page.locator('.perm-refusal form[action="/login"] input[name="board_token"]').isVisible(),who+' refusal offers no member sign-in');
    must(await page.locator('.perm-teams,#permission-member').count()===0,who+' refusal shows grants');
  };
  const denied=await page.goto(board+'/permissions');
  must(denied.status()===403,'ordinary member opened administration');
  await refusal('member');
  must((await page.locator('.perm-refusal').innerText()).includes('alice'),'member refusal does not say who is signed in');
  await shot('mobile-member-refused');
  const posted=await page.request.post(board+'/permissions/change',{headers:{Origin:board},form:{action:'preview',member:fixture.alice,workspace_role:'admin'}});
  must(posted.status()===403,'ordinary member reached the change route');
  await cookie(fixture.boardToken);
  const setup=await page.goto(board+'/permissions');
  must(setup.status()===403,'legacy board identity became Admin implicitly');
  await refusal('board login');
  must((await page.locator('body').innerText()).includes('assign the initial Admin'),'initial operator setup is not explained');
  await shot('mobile-admin-required');
  // The board login's cookie is valid, and the member sign-in still replaces it.
  await page.locator('.perm-refusal input[name="board_token"]').fill(fixture.managerToken);
  await page.locator('.perm-refusal form[action="/login"] button[type="submit"]').click();
  await page.locator('.perm-overview').waitFor();
  must((await page.evaluate(()=>location.pathname))==='/permissions','member sign-in did not return to Permissions');
  await page.locator('.perm-scroll').evaluate(el=>el.scrollTo(0,0));
  const missing=await page.goto(board+'/permissions?member=nobody-here');
  must(missing.status()===404,'unknown member did not answer 404, got '+missing.status());
  must((await page.locator('.perm-error').innerText()).includes('no longer available'),'unknown member is not explained');
  must(await page.locator('#permission-member').isVisible(),'unknown member leaves no way to choose another');
  await shot('mobile-unknown-member');
  await open(fixture.alice);
  const raw=await page.request.get(board+'/permissions?member='+fixture.alice+'&raw');
  must(raw.ok() && (await raw.text()).includes('"editor"'),'agent-readable permissions missing');
  await page.setViewportSize({width:1440,height:1200});
  must(!errors.length,'JavaScript errors: '+errors.join(';'));
  return 'permissions mobile, preview/apply, conversion, bot explanation and per-team controls passed';
}
