// Fixtures: a project named "Layout browser project" with one issue.
// Exercise the shared shell on both static pages and the live board.
async page => {
  const base = new URL(page.url()).origin;
  const teamPath = page.url().match(/\/t\/[^/]+\//)?.[0];
  if (!teamPath) throw new Error('expected a team-routed page');
  const project = 'Layout browser project';
  const button = name => page.getByRole('button', {name: 'Delete saved view ' + name, exact: true});
  const compactDelete = async name => {
    const control = button(name);
    if ((await control.innerText()).trim() || await control.locator('svg use[href="#ic-close"]').count() !== 1) throw new Error('saved-view deletion lost its cross icon');
    const box = await control.boundingBox();
    if (!box || box.width < 24 || box.height < 24 || box.width > 26 || box.height > 26) throw new Error('saved-view deletion is not a compact accessible target');
  };
  const names = ['Delete browser first', 'Delete browser second', 'Delete browser retry', 'Delete browser live'];
  await page.goto(base + teamPath + '?state=todo');
  await page.getByRole('button', {name: 'Save view', exact: true}).click();
  for (const name of names) {
    await page.getByRole('textbox', {name: 'Name this view'}).fill(name);
    await page.locator('#sv-form').getByRole('button', {name: 'Save', exact: true}).click();
    await button(name).waitFor();
  }
  await page.goto(base + teamPath + 'issues?project=' + encodeURIComponent(project));
  const layout = () => page.getByRole('navigation', {name: 'Issue layout'});
  if (await layout().getByRole('link', {name: 'List view', exact: true}).getAttribute('aria-current') !== 'page') throw new Error('list is not selected');
  if (await page.locator('#issues tbody tr').count() !== 1) throw new Error('project list lost its filter');
  await compactDelete(names[0]);
  let writes = 0;
  const countWrite = req => { if (req.url().endsWith('/views/delete')) writes++; };
  page.on('request', countWrite);
  page.once('dialog', dialog => dialog.dismiss());
  await button(names[0]).click();
  if (writes !== 0 || await button(names[0]).count() !== 1) throw new Error('cancel deleted a saved view');
  page.off('request', countWrite);
  // A stale POST snapshot must never resurrect a concurrently deleted row.
  let releaseFirst, firstFetched;
  const hold = new Promise(resolve => { releaseFirst = resolve; });
  const fetched = new Promise(resolve => { firstFetched = resolve; });
  let number = 0;
  const delayFirst = async route => {
    const current = ++number;
    const response = await route.fetch();
    if (current === 1) { firstFetched(); await hold; }
    await route.fulfill({response});
  };
  await page.route('**/views/delete', delayFirst);
  try {
    page.once('dialog', dialog => dialog.accept());
    await button(names[0]).click();
    await fetched;
    await compactDelete(names[0]);
    if (await button(names[0]).getAttribute('aria-busy') !== 'true') throw new Error('pending deletion is not announced');
    page.once('dialog', dialog => dialog.accept());
    await button(names[1]).click();
    await button(names[1]).waitFor({state: 'detached'});
    releaseFirst();
    await button(names[0]).waitFor({state: 'detached'});
    if (await button(names[1]).count()) throw new Error('stale response resurrected a deleted view');
  } finally {
    releaseFirst();
    await page.unroute('**/views/delete', delayFirst);
  }
  const refuse = route => route.fulfill({status: 503, body: 'Temporary deletion failure'});
  await page.route('**/views/delete', refuse);
  page.once('dialog', dialog => dialog.accept());
  await button(names[2]).click();
  await page.locator('#rail-views-flash').getByText('Temporary deletion failure').waitFor();
  if (!await button(names[2]).isEnabled()) throw new Error('failed delete cannot be retried');
  await compactDelete(names[2]);
  if (await button(names[2]).getAttribute('aria-busy') !== null) throw new Error('failed deletion remained busy');
  await page.unroute('**/views/delete', refuse);
  page.once('dialog', dialog => dialog.accept());
  await button(names[2]).focus();
  await page.keyboard.press('Enter');
  await button(names[2]).waitFor({state: 'detached'});
  await page.waitForFunction(() => document.activeElement?.id === 'rail-views-title');
  await layout().getByRole('link', {name: 'Board view', exact: true}).click();
  if (new URL(page.url()).searchParams.get('project') !== project) throw new Error('board lost its project');
  await page.waitForFunction(() => [...document.querySelectorAll('#board .card')].filter(el => el.checkVisibility()).length === 1);
  if (await layout().getByRole('link', {name: 'Board view', exact: true}).getAttribute('aria-current') !== 'page') throw new Error('board is not selected');
  page.once('dialog', dialog => dialog.accept());
  await button(names[3]).click();
  await button(names[3]).waitFor({state: 'detached'});
  await layout().getByRole('link', {name: 'List view', exact: true}).click();
  if (new URL(page.url()).searchParams.get('project') !== project) throw new Error('list lost its project');
  await page.reload();
  for (const name of names) {
    if (await button(name).count()) throw new Error('deleted view returned after reload');
  }
  return 'saved view deletion and project layouts browser passed';
}
