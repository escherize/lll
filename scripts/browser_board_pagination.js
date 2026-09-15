async page => {
  const base = await page.evaluate(() => location.origin);
  let phase = 'initial navigation';
  let mutation = null;
  const streamResponses = [];
  const errors = [];
  const onResponse = response => {
    // run-code has a restricted VM: URL exists in page.evaluate, not here.
    const url = response.url();
    if (url.startsWith(base + '/events?') && streamResponses.length < 8) {
      streamResponses.push({path: url.slice(base.length), status: response.status()});
    }
  };
  const onError = error => { if (errors.length < 8) errors.push(error.message); };
  page.on('response', onResponse);
  page.on('pageerror', onError);
  try {
    await page.goto(`${base}/t/BP360/`);
    const card = page.locator('.card[href="/issue/BP360-205"]');
    await card.locator('.title').waitFor();
    if (await card.locator('.title').innerText() !== 'Recovered full board') throw new Error('last-page card has stale title');
    if (await page.locator('.card').count() !== 205) throw new Error('initial board truncated');
    await card.scrollIntoViewIfNeeded();
    const draft = page.locator('#new-title');
    await draft.fill('Keep my new issue draft');
    // LLL-368: the live update can only arrive on a stream that is already
    // open. On the hosted Linux runner the subscription opened AFTER the
    // state mutation below, the event was missed, and the done card never
    // moved until reload - 3 of 4 runs. Wait for the first /events response
    // before mutating; that is what makes the later wait a test of the
    // morph rather than of runner speed.
    phase = 'stream open';
    const streamOpenedAt = Date.now();
    while (streamResponses.length === 0) {
      if (Date.now() - streamOpenedAt > 20000) throw new Error('no /events subscription within 20s of page load');
      await page.waitForTimeout(100);
    }
    phase = 'state mutation';
    const response = await page.request.post(`${base}/state`, {form: {key: 'BP360-205', state: 'done'}});
    mutation = {status: response.status(), body: (await response.text()).slice(0, 3000)};
    const failure = await page.evaluate(body =>
      new DOMParser().parseFromString(body, 'text/html').querySelector('.error-summary')?.textContent?.trim(), mutation.body);
    if (mutation.status !== 200 || failure) throw new Error('state mutation failed');
    phase = 'live done card';
    const liveStartedAt = Date.now();
    await page.locator('#col-done .card[href="/issue/BP360-205"]').waitFor({timeout: 60000});
    console.log(`live done card arrived after ${Date.now() - liveStartedAt}ms (stream opened ${liveStartedAt - streamOpenedAt}ms earlier)`);
    if (await page.locator('.card').count() !== 205) throw new Error('live board truncated');
    if (await draft.inputValue() !== 'Keep my new issue draft') throw new Error('live update lost compose draft');
    await page.screenshot({path: '/tmp/lll-360-complete-board.png'});
    phase = 'reload done card';
    await page.reload();
    await page.locator('#col-done .card[href="/issue/BP360-205"]').waitFor();
    if (await page.locator('.card').count() !== 205) throw new Error('reload truncated board');
    return 'Complete board browser passed';
  } catch (error) {
    const dom = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('.card[href="/issue/BP360-205"]')];
      return {
        path: location.pathname + location.search,
        totalCards: document.querySelectorAll('.card').length,
        mainClass: document.querySelector('.main')?.className,
        cards: cards.map(card => ({column: card.closest('.column')?.id, html: card.outerHTML.slice(0, 1000)})),
        flash: document.querySelector('#flash')?.textContent,
      };
    });
    await page.screenshot({path: '/tmp/lll-368-pagination-failure.png'});
    throw new Error(`${phase}: ${error.message}\n${JSON.stringify({mutation, streamResponses, errors, dom})}`);
  } finally {
    page.off('response', onResponse);
    page.off('pageerror', onError);
  }
}
