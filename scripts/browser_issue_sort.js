async page => {
  const origin = await page.evaluate(() => location.origin);
  await page.goto(origin + '/issues');
  const header = page.locator('th.c-title');
  for (const descending of [true, false]) {
    await header.getByRole('link', {name: 'Title', exact: true}).click();
    await page.waitForURL('**/issues?sort=' + (descending ? '-title' : 'title'));
    const titles = await page.locator('td.c-title > a').allTextContents();
    const expected = [...titles].sort();
    if (descending) expected.reverse();
    if (titles.length < 2 || JSON.stringify(titles) !== JSON.stringify(expected)) {
      throw new Error('incorrect title order: ' + JSON.stringify(titles));
    }
    if (await header.getAttribute('aria-sort') !== (descending ? 'descending' : 'ascending')) {
      throw new Error('title header does not announce its direction');
    }
  }
  if (await page.locator('th.c-state a').count()) throw new Error('State offers misleading alphabetical sorting');
  await page.screenshot({path: '/tmp/lll-106-title-sort.png'});
  return 'title header sorting verified';
}
