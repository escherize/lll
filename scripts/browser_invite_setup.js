// A real invite form -> personal CLI setup -> owned-agent instructions.
// The fixture substitutes only a scratch board URL and an evidence directory.
async page => {
  const web = '__WEB__';
  await page.locator('input[name="name"]').fill('Browser Guest');
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(web + '/me');
  const cookie = (await page.context().cookies()).find(c => c.name === 'lll_board');
  if (!cookie) throw new Error('joining did not sign the browser in');
  for (const viewport of [{width: 1280, height: 900}, {width: 390, height: 844}]) {
    await page.setViewportSize(viewport);
    await page.goto(web + '/me');
    if ((await page.locator('body').innerText()).includes(cookie.value)) throw new Error('GET exposed personal token');
    await page.getByRole('button', {name: 'Show my CLI login'}).click();
    await page.waitForLoadState('domcontentloaded');
    const text = await page.locator('body').innerText();
    for (const needed of [`lll login --url ${web} --token -`, 'already attached', 'lll bot create bot-browser-guest --team ALPHA', 'Paste that prompt into your agent']) {
      if (!text.includes(needed)) throw new Error('setup lacks: ' + needed);
    }
    if (!(await page.locator('body').innerText()).includes(cookie.value)) throw new Error('explicit reveal failed');
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error('setup overflows viewport');
    // Keep screenshots useful without retaining the test member's token.
    await page.locator('pre').filter({hasText: cookie.value}).evaluate(el => { el.textContent = '[private login token]'; });
    await page.screenshot({path: `__EVIDENCE__/setup-${viewport.width}.png`, fullPage: true});
  }
  return 'invite setup browser passed';
}
