async page => {
  const base = await page.evaluate(() => location.origin);
  await page.goto(`${base}/issue/TREEUI-2`);
  await page.locator('.issue-children h2').getByText('0/1 done').waitFor();
  await page.locator('#comment-form textarea').fill('Unfinished tree comment');
  const title = page.getByRole('button', {name: 'Edit issue title', exact: true});
  await title.focus();
  await title.press('Enter');
  await page.locator('#title-form input[name=title]').fill('Unfinished tree title');
  const response = await page.request.post(`${base}/state`, {
    headers: {Origin: base}, form: {key: 'TREEUI-3', state: 'done'}
  });
  if (!response.ok()) throw new Error(`child state write returned ${response.status()}`);
  await page.locator('.issue-children h2').getByText('1/1 done').waitFor();
  if (await page.locator('#comment-form textarea').inputValue() !== 'Unfinished tree comment') throw new Error('lost comment draft');
  if (await page.locator('#title-form input[name=title]').inputValue() !== 'Unfinished tree title') throw new Error('lost title draft');
  await page.locator('#title-form input[name=title]').press('Escape');
  for (const width of [1280, 390]) {
    await page.setViewportSize({width, height: 900});
    await page.screenshot({path: `/tmp/lll-177-tree-parent-${width}.png`, fullPage: true});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error(`parent overflow at ${width}`);
  }
  const child = page.locator('.issue-children a');
  await child.focus();
  await child.press('Enter');
  await page.locator('.issue-parent a').getByText('TREEUI-2', {exact: false}).waitFor();
  await page.screenshot({path: '/tmp/lll-177-tree-child-390.png', fullPage: true});
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('child overflow');
  const parent = page.locator('.issue-parent a');
  await parent.focus();
  await parent.press('Enter');
  await page.locator('.issue-children h2').getByText('1/1 done').waitFor();
  await page.goto(`${base}/t/TREEUI/`);
  await page.locator('.card').filter({hasText: 'Renamed second parent'}).getByText('Children 1/1 done').waitFor();
  await page.locator('.card').filter({hasText: 'Child with a long title'}).getByText('Parent TREEUI-2').waitFor();
  for (const width of [1280, 390]) {
    await page.setViewportSize({width, height: 900});
    await page.screenshot({path: `/tmp/lll-177-tree-board-${width}.png`, fullPage: true});
  }
  await page.locator('.card').filter({hasText: 'Child with a long title'}).screenshot({path: '/tmp/lll-177-tree-child-card.png'});
  return 'Issue tree browser passed';
}
