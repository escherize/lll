async page => {
  const base = await page.evaluate(() => location.origin);
  await page.goto(`${base}/t/BP360/`);
  const card = page.locator('.card[href="/issue/BP360-205"]');
  await card.locator('.title').waitFor();
  if (await card.locator('.title').innerText() !== 'Recovered full board') throw new Error('last-page card has stale title');
  if (await page.locator('.card').count() !== 205) throw new Error('initial board truncated');
  await card.scrollIntoViewIfNeeded();
  const draft = page.locator('#new-title');
  await draft.fill('Keep my new issue draft');
  await page.request.post(`${base}/state`, {form: {key: 'BP360-205', state: 'done'}});
  await page.locator('#col-done .card[href="/issue/BP360-205"]').waitFor();
  if (await page.locator('.card').count() !== 205) throw new Error('live board truncated');
  if (await draft.inputValue() !== 'Keep my new issue draft') throw new Error('live update lost compose draft');
  await page.screenshot({path: '/tmp/lll-360-complete-board.png'});
  await page.reload();
  await page.locator('#col-done .card[href="/issue/BP360-205"]').waitFor();
  if (await page.locator('.card').count() !== 205) throw new Error('reload truncated board');
  return 'Complete board browser passed';
}
