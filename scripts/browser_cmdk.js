// LLL-447: the ⌘K palette. It exists on every page, it ranks issues with the
// same engine the search page uses, and Enter lands on what is selected.
//
// Driven from a board page; e2e_web.sh substitutes the base URL, and the key
// and title of a probe issue it created for this.
async page => {
  const base = '__WEB__';
  const key = '__KEY__';
  const query = '__QUERY__';
  const open = async () => {
    await page.keyboard.press('Meta+k');
    await page.locator('#cmdk[open]').waitFor();
  };

  await page.goto(base + '/');
  await open();
  // Closed by Escape, which is the dialog's own behaviour, not ours.
  await page.keyboard.press('Escape');
  // A closed <dialog> is hidden, not absent: waiting for it to be VISIBLE
  // would wait out the timeout on a palette that closed correctly.
  await page.locator('#cmdk').waitFor({state: 'hidden'});

  await open();
  // With nothing typed every destination is offered, and the first is
  // selected so Enter always has an answer.
  const gotoCount = await page.locator('#cmdk-goto a:visible').count();
  if (gotoCount < 6) throw new Error('palette offers no destinations: ' + gotoCount);
  if (await page.locator('#cmdk .cmdk-sel').count() !== 1) throw new Error('palette opened with no selection');

  // Typing filters those destinations in the browser: they are this page's
  // own links, so narrowing them needs no round trip.
  await page.keyboard.type('Members', {delay: 40});
  // Measured as PAINTED, not as the hidden property: `display: flex` on a
  // row once beat the user agent's [hidden] rule, so the code believed rows
  // were filtered out while they were still on screen.
  await page.waitForFunction(() => {
    const rows = [...document.querySelectorAll('#cmdk-goto [data-cmdk-item]')];
    const painted = rows.filter(r => r.offsetParent !== null);
    return painted.length > 0 && painted.length < rows.length;
  });
  await page.locator('#cmdk-goto a:visible', {hasText: 'Members'}).first().click();
  await page.waitForURL(/\/settings\/members$/);

  // The palette is on the settings page too, and its search half asks the
  // server, which answers with this team's issues, ranked by the engine the
  // search page uses.
  await open();
  await page.keyboard.type(query, {delay: 40});
  const hit = page.locator(`#cmdk-results a[href="/issue/${key}"]`);
  await hit.waitFor();
  await page.screenshot({path: '/tmp/lll-447-cmdk.png'});
  // The arriving answer takes the selection even though a destination was
  // selected while it was in flight: Enter follows the best match, not
  // whatever was highlighted a moment ago.
  await page.waitForFunction(
    k => document.querySelector('#cmdk .cmdk-sel')?.getAttribute('href') === '/issue/' + k,
    key,
  );
  await page.keyboard.press('Enter');
  await page.waitForURL(new RegExp('/issue/' + key + '$'));

  // /issues loads no Datastar at all (a table needs no JavaScript), so the
  // palette's search has to work with navigation.js alone. This is the whole
  // reason the fragment is plain HTML rather than an SSE patch.
  await page.goto(base + '/issues');
  const scripts = await page.evaluate(() => [...document.scripts].map(s => s.src.split('/').pop()));
  if (scripts.includes('datastar.js')) throw new Error('the issues page started loading Datastar');
  await open();
  await page.keyboard.type(query, {delay: 40});
  await page.locator(`#cmdk-results a[href="/issue/${key}"]`).waitFor();
  await page.keyboard.press('Escape');

  // A query that matches nothing says so once, naming the query.
  await open();
  await page.keyboard.type('zzzznope', {delay: 20});
  await page.locator('#cmdk-results .cmdk-empty').waitFor();
  if (await page.locator('#cmdk-none:visible').count() !== 0) {
    throw new Error('two empty messages at once');
  }
  await page.keyboard.press('Escape');
  return 'cmdk palette browser passed';
}
