async page => {
  const form = page.locator('#state-form');
  const select = form.locator('select[name="state"]');
  const original = await select.inputValue();
  const target = original === 'done' ? 'todo' : 'done';
  const beforeURL = page.url();
  // FormValue takes the first submitted value. Only this browser fixture
  // gets the invalid field; the real Datastar handler and server still run.
  await form.evaluate(el => {
    const field = document.createElement('input');
    field.type = 'hidden';
    field.name = 'state';
    field.value = 'bogus';
    field.dataset.failureProbe = 'true';
    el.prepend(field);
  });
  let selectionAfterFailure;
  try {
    const response = page.waitForResponse(r => r.url().endsWith('/state') && r.request().method() === 'POST');
    await select.selectOption(target);
    const result = await response;
    if (result.status() !== 200 || !(result.headers()['content-type'] || '').includes('text/event-stream')) {
      throw new Error('expected the normal SSE action response');
    }
    await page.locator('#flash').getByText('unknown state', {exact: false}).waitFor();
    if (page.url() !== beforeURL) throw new Error('failed state action navigated');
    selectionAfterFailure = await select.inputValue();
    await page.screenshot({path: '/tmp/lll-131-state.png'});
  } finally {
    await form.locator('[data-failure-probe]').evaluateAll(fields => fields.forEach(field => field.remove()));
  }
  // Reload proves server truth independently of the edited DOM control.
  await page.reload();
  if (await select.inputValue() !== original) throw new Error('failed state action persisted a change');
  return {result: 'state failure shown in browser and stored state unchanged', original, target, selectionAfterFailure};
}
