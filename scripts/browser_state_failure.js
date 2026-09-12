async page => {
  const beforeURL = page.url();
  const comment = page.locator('#comment-form textarea');
  const draft = 'Unrelated comment draft — keep this';
  await comment.fill(draft);
  const controls = [
    ['state-form', 'state', 'unknown state'],
    ['prio-form', 'priority', 'unknown priority'],
    ['assignee-form', 'assignee', 'unknown member'],
    ['project-form', 'project', 'unknown project'],
    ['labels-form', 'labels', 'unknown label']
  ];
  for (const [id, field, error] of controls) {
    const form = page.locator('#' + id);
    const checkbox = field === 'labels';
    const control = checkbox ? form.locator('input[type=checkbox]').first() : form.locator('select');
    const original = checkbox ? await control.isChecked() : await control.inputValue();
    await form.evaluate((el, name) => {
      const input = document.createElement('input');
      input.type = 'hidden'; input.name = name; input.value = 'bogus';
      input.dataset.failureProbe = 'true'; el.prepend(input);
    }, field);
    try {
      const response = page.waitForResponse(r => r.url().endsWith('/' + field) && r.request().method() === 'POST').catch(error => { throw new Error(field + ': ' + error.message); });
      if (checkbox) {
        await form.locator('.lab-add').click();
        await control.locator("..").click();
      } else {
        const target = await control.locator('option').evaluateAll((options, value) => options.find(o => o.value !== value)?.value, original);
        if (target === undefined) throw new Error(`no alternate ${field} fixture`);
        await control.selectOption(target);
      }
      const result = await response;
      if (result.status() !== 200 || !(result.headers()['content-type'] || '').includes('text/event-stream')) {
        throw new Error('expected normal SSE action response');
      }
      await page.locator('#flash').getByText(error, {exact: false}).waitFor();
      // Recovery replaces the panel, removing the injected field. Wait for
      // that response patch, not just the earlier error flash event.
      await form.locator('[data-failure-probe]').waitFor({state: 'detached'});
      const restored = checkbox ? await control.isChecked() : await control.inputValue();
      if (restored !== original) throw new Error(`failed ${field} left an unsaved control value`);
      if (page.url() !== beforeURL || await comment.inputValue() !== draft) throw new Error('recovery disturbed navigation or comment draft');
      if (field === 'state') await page.screenshot({path: '/tmp/lll-131-state.png'});
    } finally {
      await form.locator('[data-failure-probe]').evaluateAll(fields => fields.forEach(field => field.remove()));
    }
  }
  // If the record cannot be read, do not display the rejected value as
  // current. The error remains visible and unrelated drafts remain usable.
  const form = page.locator('#state-form');
  await form.evaluate(el => {
    const input = document.createElement('input');
    input.type = 'hidden'; input.name = 'key'; input.value = 'MISSINGPROBE-999999';
    el.prepend(input);
  });
  const select = form.locator('select');
  const original = await select.inputValue();
  await select.selectOption(original === 'done' ? 'todo' : 'done');
  await page.getByText('Property values could not be refreshed. Reload to retry.', {exact: true}).waitFor();
  if (await comment.inputValue() !== draft) throw new Error('unavailable-property fallback lost comment draft');
  await page.reload();
  if (await page.locator('#state-form select').inputValue() !== original) throw new Error('failed state action persisted a change');
  return 'state failure shown in browser and stored state unchanged; all five property controls reconcile; unavailable fallback preserves draft';
}
