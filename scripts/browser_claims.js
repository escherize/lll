async page => {
  const base = await page.evaluate(() => location.origin);
  const board = await page.context().newPage();
  try {
    await board.goto(`${base}/t/CL185/`);
    await page.goto(`${base}/issue/CL185-1`);
    const claim = page.locator('#claim-form button');
    await claim.waitFor();
    const actor = (await claim.innerText()).replace(/^Claim as /, '');
    if (!actor) throw new Error('claim action did not name its actor');
    await page.locator('#comment-form textarea').fill('Keep my claim review comment');
    await page.locator('.issue-main h1').click();
    await page.locator('#title-form input[name=title]').fill('Keep my claim review title');
    const memberID = await page.locator('#claim-form input[name=member_id]').inputValue();
    const forged = await page.request.post(`${base}/claim`, {form: {key: 'CL185-1', member_id: 'stale-actor'}});
    if (!(await forged.text()).includes('identity changed')) throw new Error('stale board actor accepted');
    await page.request.post(`${base}/claim`, {form: {key: 'CL185-1', member_id: memberID}});
    await page.locator('#release-form button').waitFor();
    if (!await page.locator('#title-form input[name=title]').isVisible()) throw new Error('remote claim closed title draft');
    if (await page.locator('#title-form input[name=title]').inputValue() !== 'Keep my claim review title') throw new Error('remote claim lost title draft');
    await page.locator('#title-form input[name=title]').press('Escape');
    await board.locator('.card-claim').getByText('Claimed: ' + actor, {exact: true}).waitFor();
    const oldClaim = await page.locator('#release-form input[name=claim_id]').inputValue();
    await page.locator('#release-form button').focus();
    await page.locator('#release-form button').press('Enter');
    await claim.waitFor();
    await board.locator('.card-claim').waitFor({state: 'detached'});
    await claim.click();
    await page.locator('#release-form button').waitFor();
    const replacement = await page.locator('#release-form input[name=claim_id]').inputValue();
    if (replacement === oldClaim) throw new Error('replacement reused a claim ID');
    const stale = await page.request.post(`${base}/release`, {form: {key: 'CL185-1', claim_id: oldClaim}});
    if (!(await stale.text()).includes('claim changed')) throw new Error('stale release was not rejected');
    if (await page.locator('#comment-form textarea').inputValue() !== 'Keep my claim review comment') throw new Error('lost comment draft');
    if (await page.locator('#title-form input[name=title]').inputValue() !== 'Keep my claim review title') throw new Error('lost title draft');
    for (const width of [1280, 390]) {
      await page.setViewportSize({width, height: 1000});
      await page.screenshot({path: `/tmp/lll-185-claim-${width}.png`, fullPage: true});
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('claim control overflow');
    }
    await board.screenshot({path: '/tmp/lll-185-board.png'});
    await page.locator('#release-form button').click();
    await claim.waitFor();
    return 'Board claim controls passed';
  } finally {
    await board.close();
  }
}
