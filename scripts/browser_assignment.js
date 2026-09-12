async page => {
  const base = await page.evaluate(() => location.origin);
  await page.goto(`${base}/issue/ASGN-1`);
  const select = page.locator('#assignee-form select');
  const comment = page.locator('#comment-form textarea');
  const original = await select.inputValue();
  if (!original) throw new Error('assignment fixture has no holder');
  await comment.fill('Keep my assignment review draft');
  const other = await select.locator('option').evaluateAll((options, value) => options.find(o => o.value && o.value !== value)?.value, original);
  if (!other) throw new Error('assignment fixture needs a second member');
  await select.selectOption(other);
  await page.locator('#flash').getByText('is claimed by', {exact: false}).waitFor();
  await page.waitForFunction(value => document.querySelector('#assignee-form select').value === value, original);
  if (await comment.inputValue() !== 'Keep my assignment review draft') throw new Error('refusal lost comment draft');
  await page.screenshot({path: '/tmp/lll-358-assignment-refused.png'});
  const response = page.waitForResponse(r => r.url().endsWith('/assignee') && r.request().method() === 'POST');
  await select.selectOption('');
  const result = await response;
  if (result.status() !== 200) throw new Error('clear assignment request failed');
  await page.waitForFunction(() => document.querySelector('#flash').hidden);
  if (await comment.inputValue() !== 'Keep my assignment review draft') throw new Error('successful clear lost comment draft');
  await page.reload();
  if (await select.inputValue() !== '') throw new Error('assignment clear did not persist');
  return 'Assignment browser passed: claimed reassignment refused, control restored, clear persisted, draft preserved';
}
