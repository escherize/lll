async page => {
  const form = page.locator('#ni-form');
  const alert = form.locator('#ni-flash');
  await alert.getByText('unknown state', {exact: false}).waitFor();
  if (await alert.getAttribute('role') !== 'alert' || await alert.getAttribute('aria-atomic') !== 'true') {
    throw new Error('create error lacks alert semantics');
  }
  if (await form.getAttribute('aria-describedby') !== 'ni-flash') throw new Error('form does not reference its error');
  const title = await page.locator('#ni-title').inputValue();
  const description = await page.locator('#ni-desc').inputValue();
  for (const width of [1280, 390]) {
    await page.setViewportSize({width, height: 900});
    await alert.scrollIntoViewIfNeeded();
    const unobscured = await alert.evaluate(el => {
      const box = el.getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      return box.width > 0 && box.height > 0 && box.left >= 0 && box.right <= innerWidth && (hit === el || el.contains(hit));
    });
    if (!unobscured) throw new Error(`create alert obscured at ${width}px`);
    await page.screenshot({path: `/tmp/lll-349-create-${width}.png`});
  }
  await page.setViewportSize({width: 1280, height: 800});
  // Enter follows the same create handler and must preserve the entire draft.
  const response = page.waitForResponse(r => r.url().endsWith('/create') && r.request().method() === 'POST');
  await page.locator('#ni-title').press('Enter');
  await response;
  await alert.getByText('unknown state', {exact: false}).waitFor();
  if (await page.locator('#ni-title').inputValue() !== title || await page.locator('#ni-desc').inputValue() !== description) {
    throw new Error('keyboard retry lost the create draft');
  }
  // Remove the fixture-only invalid field before reopening the form.
  await form.locator('input[type="hidden"][name="state"]').evaluateAll(fields => fields.forEach(field => field.remove()));
  await page.locator('#ni-title').press('Escape');
  await page.locator('#ni-expand').click();
  await page.waitForFunction(() => {
    const error = document.getElementById('ni-flash');
    return error.hidden && error.textContent === '';
  });
  await page.locator('#ni-title').press('Escape');
  return 'create error readable inside dialog; keyboard retry and fresh-open clearing passed';
}
