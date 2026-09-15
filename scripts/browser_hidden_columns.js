// LLL-383: the unhide round trip, which only a browser can see.
//
// The server-side assertions around ?hide= all passed while this was broken.
// They prove the URL renders the right classes; they cannot see that clicking
// the rail's "Show Backlog column" button navigated to a clean URL and then had
// the saved view put the hide straight back, leaving the column unshowable by
// its own affordance.
//
// The last hidden column is the case that failed and the common one - people
// hide one. With another still hidden the query string is non-empty, the
// saved-view restore never fires, and the bug does not appear.
async page => {
  // No `new URL(...)`: the run-code VM has no URL global, which LLL-368
  // already recorded the hard way - it crashes asynchronously and the failure
  // arrives detached from the line that caused it.
  const base = page.url().match(/^https?:\/\/[^/]+/)[0];
  const hidden = async id =>
    !(await page.locator(id).isVisible().catch(() => false));

  // The last hidden column: unhiding leaves no query string, which is exactly
  // what data-init treats as "restore the saved view".
  await page.goto(base + '/t/ENG/?hide=done');
  await page.waitForLoadState('load');
  if (!(await hidden('#col-done'))) throw new Error('?hide=done did not hide the done column');

  await page.locator('#hidden-rail button.hr-done').click();
  await page.waitForLoadState('load');
  await page.waitForTimeout(500);
  if (await hidden('#col-done')) {
    const view = await page.evaluate(() => localStorage.getItem('lllView'));
    throw new Error(`the last hidden column stayed hidden; url=${page.url()} lllView=${view}`);
  }
  const stored = await page.evaluate(() => localStorage.getItem('lllView'));
  if (stored) throw new Error(`the saved view still holds "${stored}" and will restore the hide`);

  // Restoring a column must not take the ordering with it.
  await page.goto(base + '/t/ENG/?hide=done&order=created');
  await page.waitForLoadState('load');
  await page.locator('#hidden-rail button.hr-done').click();
  await page.waitForLoadState('load');
  await page.waitForTimeout(500);
  if (!page.url().includes('order=created')) {
    throw new Error(`unhiding discarded the ordering: ${page.url()}`);
  }

  // One of two: the other stays hidden, so this is not "clear everything".
  await page.goto(base + '/t/ENG/?hide=done,todo');
  await page.waitForLoadState('load');
  await page.locator('#hidden-rail button.hr-done').click();
  await page.waitForLoadState('load');
  await page.waitForTimeout(500);
  if (await hidden('#col-done')) throw new Error('unhiding one of two did not show it');
  if (!(await hidden('#col-todo'))) throw new Error('unhiding one of two also showed the other');

  await page.goto(base + '/t/ENG/');
  await page.waitForLoadState('load');
  // LLL-375: the saved view is a cookie the SERVER reads, so the bare URL
  // paints the hidden column on the FIRST render — the URL never changes,
  // where the old localStorage restore replaced it with ?hide=.
  await page.goto(base + '/t/ENG/?hide=todo');
  await page.waitForLoadState('load');
  await page.goto(base + '/t/ENG/');
  await page.waitForLoadState('load');
  await page.waitForTimeout(700);
  if (page.url().includes('?')) throw new Error(`the bare board redirected: ${page.url()}`);
  if (!(await hidden('#col-todo'))) {
    throw new Error('the saved-view cookie did not hide todo on the bare board');
  }
  const cookie = await page.evaluate(() => document.cookie);
  if (!cookie.includes('lll_view_ENG=todo')) {
    throw new Error(`the saved-view cookie is missing: ${cookie}`);
  }
  // Clearing the view — the cookie and the old localStorage key — restores
  // every column, the same bargain Clear and unhide-the-last-column offer.
  await page.evaluate(() => {
    document.cookie = 'lll_view_ENG=; Max-Age=0; Path=/';
    localStorage.clear();
  });
  await page.goto(base + '/t/ENG/');
  await page.waitForLoadState('load');
  await page.waitForTimeout(500);
  if (await hidden('#col-todo')) throw new Error('a cleared saved view still hides todo');
  return 'hidden column round trip verified';
}
