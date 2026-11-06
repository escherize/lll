// Fixtures: Grouping Alpha/Beta (planned), Started/Paused/Completed/Cancelled;
// PGP has a started project, and PG0 is empty. No project writes in this driver.
async page => {
  // The CI run-code VM has no URL host global; URL reads belong to the page.
  const base = await page.evaluate(() => location.origin);
  const teamPath = page.url().match(/\/t\/[^/]+\//)?.[0];
  if (!teamPath) throw new Error('expected a team-routed page');
  const path = base + teamPath + 'projects';
  const group = (status, target = page) => target.locator(`.pj-group[data-project-status="${status}"]`);
  const expectOpen = async (status, open, target = page) => {
    await target.waitForFunction(({status, open}) => document.querySelector(`.pj-group[data-project-status="${status}"]`)?.open === open, {status, open});
  };
  await page.goto(path);
  const statuses = await page.locator('.pj-group').evaluateAll(groups => groups.map(el => el.dataset.projectStatus));
  if (statuses.join(',') !== 'planned,started,paused,completed,cancelled') throw new Error('project status groups are out of lifecycle order');
  for (const status of statuses) await expectOpen(status, true);
  for (const [status, name] of [['planned', 'Alpha'], ['planned', 'Beta'], ['started', 'Started'], ['paused', 'Paused'], ['completed', 'Completed'], ['cancelled', 'Cancelled']]) {
    await group(status).getByText('Grouping ' + name, {exact: true}).waitFor();
  }
  const plannedNames = await group('planned').locator('.pj-name').allTextContents();
  if (plannedNames.indexOf('Grouping Alpha') >= plannedNames.indexOf('Grouping Beta')) throw new Error('grouping lost alphabetical project order');
  const count = await group('planned').locator('.pj-row').count();
  if ((await group('planned').locator('summary .pj-count').innerText()).trim() !== count + ' projects') throw new Error('group project count is wrong');
  await group('started').locator('summary').click();
  await expectOpen('started', false);
  if (await group('started').getByText('Grouping Started', {exact: true}).isVisible()) throw new Error('collapsed group still exposes its rows');
  await page.reload();
  if (await group('started').evaluate(el => el.open)) throw new Error('collapsed project group was not remembered after reload');
  await group('started').locator('summary').press('Enter');
  await expectOpen('started', true);
  await page.reload();
  await expectOpen('started', true);
  for (const status of ['planned', 'started']) await group(status).locator('summary').click();
  await page.reload();
  for (const status of ['planned', 'started']) await expectOpen(status, false);
  await page.goto(base + '/t/PGP/projects');
  await expectOpen('started', true);
  await group('started').locator('summary').click();
  await page.reload();
  await expectOpen('started', false);
  await page.goto(path);
  for (const status of ['planned', 'started']) await expectOpen(status, false);
  await group('planned').locator('summary').press('Space');
  await expectOpen('planned', true);
  await page.reload();
  await expectOpen('planned', true);
  await expectOpen('started', false);
  await page.goto(base + '/projects');
  await expectOpen('started', false);
  const raw = await page.request.get(path + '?raw');
  if (!raw.ok() || !(await raw.text()).includes('Grouping Started')) throw new Error('collapse hid projects from raw output');
  await group('planned').locator('.pj-row').filter({hasText: 'Grouping Alpha'}).click();
  if ((await page.evaluate(() => new URLSearchParams(location.search).get('project'))) !== 'Grouping Alpha') throw new Error('grouping broke the project drilldown');
  await page.goto(path);
  await expectOpen('started', false);
  const secondTab = await page.context().newPage();
  try {
    await secondTab.goto(path);
    await expectOpen('started', false, secondTab);
  } finally { await secondTab.close(); }

  const key = await page.locator('#projects').getAttribute('data-project-groups-key');
  await page.evaluate(key => localStorage.setItem(key + '.started', 'invalid'), key);
  await page.reload();
  await page.locator('#pj-preference-error').waitFor();
  await expectOpen('started', true);
  await group('started').locator('summary').click();
  await expectOpen('started', false);
  await page.reload();
  await expectOpen('started', false);

  for (const method of ['getItem', 'setItem']) {
    const blocked = await page.context().newPage();
    try {
      await blocked.addInitScript(method => {
        Storage.prototype[method] = () => { throw new DOMException('Storage disabled for this test', 'SecurityError'); };
      }, method);
      await blocked.goto(path);
      const initial = await group('planned', blocked).evaluate(el => el.open);
      await group('planned', blocked).locator('summary').click();
      await expectOpen('planned', !initial, blocked);
      await blocked.locator('#pj-preference-error').waitFor();
    } finally { await blocked.close(); }
  }
  const native = await page.context().browser().newContext({javaScriptEnabled: false});
  try {
    await native.addCookies(await page.context().cookies());
    const noScript = await native.newPage();
    await noScript.goto(path);
    await group('planned', noScript).getByText('Grouping Alpha', {exact: true}).waitFor();
    await group('planned', noScript).locator('summary').click();
    if (await group('planned', noScript).getByText('Grouping Alpha', {exact: true}).isVisible()) throw new Error('groups require JavaScript to collapse');
  } finally { await native.close(); }
  await page.goto(base + '/t/PG0/projects');
  await page.getByText('No projects yet.', {exact: false}).waitFor();
  if (await page.locator('.pj-group').count()) throw new Error('empty team has empty status groups');
  await page.goto(path);
  return 'project grouping passed: lifecycle order, counts, collapse/reopen, reload/new tab, team isolation, keyboard, raw/drilldown, unavailable storage and no JavaScript';
}
