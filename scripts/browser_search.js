async page => {
  const field = page.locator('.search-bar input');
  const base = await page.locator('.search-bar').getAttribute('action');
  const origin = await page.evaluate(() => location.origin);
  await page.evaluate(() => document.body.dataset.searchProbe = 'kept');

  // Hold an actual older response until the newer query has rendered. This
  // exercises cancellation across URLs, not two requests with the same q.
  let releaseOld;
  let oldReady;
  let oldDone;
  const release = new Promise(resolve => releaseOld = resolve);
  const ready = new Promise(resolve => oldReady = resolve);
  const done = new Promise(resolve => oldDone = resolve);
  let oldAborted = false;
  const failed = request => {
    if (request.url().includes('fragment=1&q=Already')) oldAborted = true;
  };
  page.on('requestfailed', failed);
  const intercept = async route => {
    if (!route.request().url().includes('fragment=1&q=Already')) {
      await route.continue();
      return;
    }
    try {
      const response = await route.fetch();
      oldReady();
      await release;
      await route.fulfill({response});
    } finally {
      oldDone();
    }
  };
  await page.route('**/search?fragment=1&**', intercept);
  try {
    await field.fill('Already');
    await ready;
    await field.fill('Web board');
    await page.locator('.sr-title').filter({hasText: 'Web board issue'}).waitFor();
    await page.waitForFunction(() => document.title === 'lll - ENG search "Web board"');
    releaseOld();
    await done;
    // Flush browser work after the delayed response has been released.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    if (!oldAborted) throw new Error('the previous query request was not canceled');
    if (await page.locator('.sr-title').filter({hasText: 'Already in progress'}).count()) throw new Error('old results replaced the current query');
    if (await page.title() !== 'lll - ENG search "Web board"') throw new Error('old response replaced the tab title');
    if (!page.url().endsWith(base + '?q=Web%20board')) throw new Error('query URL drifted');
  } finally {
    releaseOld();
    await page.unroute('**/search?fragment=1&**', intercept);
    page.off('requestfailed', failed);
  }

  // Escaping and whitespace use the same server title template on a live
  // update and a full navigation. Empty typing must clear title and results.
  const query = '  "<& snow ☃  ';
  await field.fill(query);
  const expected = 'lll - ENG search "' + query.trim() + '"';
  await page.waitForFunction(title => document.title === title, expected);
  await field.fill('');
  await page.waitForFunction(() => document.title === 'lll - ENG search');
  if (await page.locator('.sr-title').count()) throw new Error('empty query kept results');
  if (!page.url().endsWith(base)) throw new Error('empty query kept URL parameters');
  if (await page.evaluate(() => document.body.dataset.searchProbe) !== 'kept') throw new Error('live search reloaded');
  await page.screenshot({path: '/tmp/lll-121-search.png'});
  await page.goto(origin + base + '?q=' + encodeURIComponent(query));
  if (await page.title() !== expected) throw new Error('page-load and live titles differ');
  return 'search ordering and titles verified';
}
