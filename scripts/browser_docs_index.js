// LLL-643: the docs index. The rail's Docs row reaches it, the kind and text
// filters are GET navigations whose URL is the whole state, and the list fits
// a phone: markup assertions cannot see a row pushed off the right edge.
// Runs from any page of the team under test; that team needs at least one
// decision doc and one doc of another kind.
async page => {
  const origin = await page.evaluate(() => location.origin);
  const team = (await page.evaluate(() => location.pathname)).match(/^\/t\/([^/]+)\//);
  if (!team) throw new Error('start from a team page, not ' + await page.evaluate(() => location.pathname));
  const base = `/t/${team[1]}/docs`;
  const rows = () => page.locator('#docs a.dl-row');
  for (const [width, height] of [[1280, 800], [390, 844]]) {
    await page.setViewportSize({width, height});
    await page.goto(origin + `/t/${team[1]}/`);
    if (width < 720) await page.getByRole('button', {name: 'Navigation', exact: true}).click();
    await page.locator('#rail').getByRole('link', {name: 'Docs', exact: true}).click();
    await page.waitForURL('**' + base);
    const all = await rows().count();
    if (all < 2) throw new Error(`${width}px: expected at least two docs, got ${all}`);
    // Every row fits the viewport: no sideways scroll, no clipped column.
    const overflow = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const wide = [...document.querySelectorAll('#docs a.dl-row, .itbl-bar')]
        .filter(el => el.getBoundingClientRect().right > vw + 1).length;
      return {wide, scroll: document.scrollingElement.scrollWidth > vw + 1};
    });
    if (overflow.wide || overflow.scroll) throw new Error(`${width}px: the docs list overflows: ` + JSON.stringify(overflow));
    // Kind: the select submits as ?kind=, and only that kind remains.
    await page.locator('#f-kind').selectOption('decision');
    await page.getByRole('button', {name: 'Filter', exact: true}).click();
    await page.waitForURL(`**${base}?kind=decision&q=`);
    const kinds = await page.locator('#docs .dl-kind').allTextContents();
    if (!kinds.length || kinds.some(k => k.trim() !== 'Decision')) throw new Error(`${width}px: kind filter kept ` + JSON.stringify(kinds));
    // Text: narrows on slug or title, and a miss says so with a way back.
    await page.locator('#f-kind').selectOption('');
    await page.locator('#f-q').fill('zzzz-no-such-doc');
    await page.getByRole('button', {name: 'Filter', exact: true}).click();
    await page.waitForURL(`**${base}?kind=&q=zzzz-no-such-doc`);
    if (await rows().count() !== 0) throw new Error(`${width}px: a text miss still lists docs`);
    await page.getByRole('link', {name: 'Show every doc', exact: true}).click();
    await page.waitForURL('**' + base);
    if (await rows().count() !== all) throw new Error(`${width}px: clearing the filter did not restore the list`);
    // A row opens its doc page.
    const href = await rows().first().getAttribute('href');
    await rows().first().click();
    await page.waitForURL('**' + href);
  }
  await page.setViewportSize({width: 1280, height: 800});
  return 'docs index verified';
}
