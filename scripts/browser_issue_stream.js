async page => {
  const base = await page.evaluate(() => location.origin);
  const key = 'SSE58-1';
  await page.goto(`${base}/issue/${key}`);
  await page.locator('#issue-description svg').waitFor();
  // Establish a metadata barrier after the initial stream snapshot.
  await page.request.post(`${base}/title`, {form: {key, title: 'Stream browser ready'}});
  await page.locator('.issue-main h1').getByText('Stream browser ready', {exact: true}).waitFor();
  await page.locator('#issue-description svg').waitFor();
  await page.evaluate(() => {
    window.keptDescription = document.querySelector('#issue-description');
    window.keptDiagram = document.querySelector('#issue-description svg');
  });
  await page.locator('#comment-form textarea').fill('Unfinished comment');
  await page.locator('.issue-main h1').click();
  await page.locator('#title-form input[name=title]').fill('Unfinished title');
  await page.request.post(`${base}/priority`, {form: {key, priority: 'urgent'}});
  await page.waitForFunction(() => document.querySelector('#prio-form select').value === 'urgent');
  if (!await page.evaluate(() => window.keptDescription === document.querySelector('#issue-description') && window.keptDiagram === document.querySelector('#issue-description svg'))) throw new Error('metadata replaced description or diagram');
  if (await page.locator('#comment-form textarea').inputValue() !== 'Unfinished comment') throw new Error('lost comment draft');
  if (await page.locator('#title-form input[name=title]').inputValue() !== 'Unfinished title') throw new Error('lost title draft');
  await page.locator('#title-form input[name=title]').press('Escape');
  for (const width of [1280, 390]) {
    await page.setViewportSize({width, height: 900});
    await page.screenshot({path: `/tmp/lll-58-stream-${width}.png`, fullPage: true});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error(`overflow at ${width}`);
  }
  return 'Issue stream browser passed';
}
