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
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({width, height: 900});
    await alert.scrollIntoViewIfNeeded();
    const unobscured = await alert.evaluate(el => {
      const box = el.getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      return box.width > 0 && box.height > 0 && box.left >= 0 && box.right <= innerWidth && (hit === el || el.contains(hit));
    });
    if (!unobscured) throw new Error(`create alert obscured at ${width}px`);
    if (width <= 390) {
      const readableFooter = await form.locator('.ni-foot').evaluate(el => {
        const oneLine = selector => {
          const item = el.querySelector(selector);
          return item.getBoundingClientRect().height <= parseFloat(getComputedStyle(item).lineHeight) + 1;
        };
        const create = el.querySelector('#ni-create');
        return oneLine('.ni-hint') && oneLine('.ni-more') && create.getBoundingClientRect().height < 40;
      });
      if (!readableFooter) throw new Error(`create footer text is squeezed at ${width}px`);
    }
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
  // An assignee outside the viewer's roster is refused by name (LLL-675),
  // inside the dialog, without the HTTP envelope.
  await form.evaluate(el => {
    const input = document.createElement('input');
    input.type = 'hidden'; input.name = 'assignee'; input.value = 'invalid-member';
    input.dataset.errorProbe = '1'; el.prepend(input);
  });
  await page.locator('#ni-title').press('Enter');
  await alert.getByText("unknown member 'invalid-member'", {exact: false}).waitFor();
  const validation = await alert.innerText();
  if (validation.includes('http://') || validation.includes('Bad Request') || validation.includes('"data"')) throw new Error('validation exposed HTTP envelope');
  if (await page.locator('#ni-title').inputValue() !== title || await page.locator('#ni-desc').inputValue() !== description) throw new Error('validation lost create draft');
  await page.screenshot({path: '/tmp/lll-359-validation.png'});
  await form.locator('[data-error-probe]').evaluateAll(fields => fields.forEach(field => field.remove()));
  await page.locator('#ni-title').press('Escape');
  await page.locator('#ni-expand').click();
  await page.waitForFunction(() => {
    const error = document.getElementById('ni-flash');
    return error.hidden && error.textContent === '';
  });
  await page.locator('#ni-title').press('Escape');
  await page.locator('#ni-expand').click();
  const assignee = form.getByRole('combobox', {name: 'Assignee', exact: true});
  const project = form.getByRole('combobox', {name: 'Project', exact: true});
  await assignee.selectOption({label: 'A very long member name that should fit inside the full create dialog on a mobile screen'});
  await project.selectOption({label: 'A very long project name that should fit inside the full create dialog on a mobile screen'});
  for (const width of [320, 390, 1280]) {
    await page.setViewportSize({width, height: 900});
    const contained = await page.locator('.ni-dialog').evaluate(el => {
      const box = el.getBoundingClientRect();
      return [...el.querySelectorAll('select')].every(control => {
        const rect = control.getBoundingClientRect();
        return rect.left >= box.left && rect.right <= box.right;
      });
    });
    if (!contained) throw new Error(`create dialog select overflow at ${width}px`);
  }
  await assignee.selectOption('');
  await project.selectOption('');
  await page.locator('#ni-title').press('Escape');
  const quickState = page.getByRole('combobox', {name: 'Issue state', exact: true});
  const originalState = await quickState.inputValue();
  await quickState.selectOption('in-progress');
  if (await quickState.inputValue() !== 'in-progress') throw new Error('named quick-create state selector did not retain selection');
  await quickState.selectOption(originalState);
  const opener = page.getByRole('button', {name: 'Open the full create form', exact: true});
  for (const dismissal of ['Escape', 'Close', 'Cancel']) {
    await opener.click();
    await page.waitForFunction(() => document.activeElement?.id === 'ni-title');
    if (dismissal === 'Escape') await page.locator('#ni-title').press('Escape');
    else await page.locator('#ni-form').getByRole('button', {name: dismissal, exact: true}).click();
    await page.waitForFunction(() => document.activeElement?.id === 'ni-expand');
  }
  await page.evaluate(() => document.activeElement.blur());
  await page.keyboard.press('c');
  await page.waitForFunction(() => document.activeElement?.id === 'ni-title');
  await page.locator('#ni-title').press('Escape');
  await page.locator('#ni-title').waitFor({state: 'hidden'});
  return 'create error readable inside dialog; keyboard retry and fresh-open clearing passed';
}
