async page => {
  for (const kind of ['label', 'member', 'project']) {
    const row = name => page.locator('form.set-row').filter({
      has: page.locator(`input[name="name"][value="${name}"]`)
    });
    const first = row(`Draft ${kind} A`);
    const other = row(`Draft ${kind} B`);
    const otherInput = other.locator('input[name="name"]');
    const otherID = await other.locator('..').getAttribute('id');
    if (!otherID?.startsWith(`set-${kind}-`)) throw new Error('missing stable row wrapper');
    await otherInput.fill(`Unsaved ${kind} B`);
    if (kind === 'label') await other.getByLabel('Colour', {exact: true}).fill('#123456');
    if (kind === 'project') await other.getByLabel('Project status').selectOption('paused');
    await page.getByLabel('New label name', {exact: true}).fill('Unsaved new label');
    await page.getByLabel('New project name', {exact: true}).fill('Unsaved new project');
    await page.getByLabel('Status for the new project').selectOption('started');
    await page.locator('#set-name').fill('Unsaved team name');
    // The rename moves this row past its neighbour in the server's sort.
    await first.locator('input[name="name"]').fill(`Z saved ${kind} A`);
    await first.getByRole('button', {name: 'Save', exact: true}).click();
    await row(`Z saved ${kind} A`).waitFor();
    const retained = page.locator('#' + otherID);
    const expectValue = async (input, expected) => {
      if (await input.inputValue() !== expected) throw new Error(`draft lost after ${kind} save: ${expected}`);
    };
    await expectValue(retained.locator('input[name="name"]'), `Unsaved ${kind} B`);
    if (kind === 'label') await expectValue(retained.getByLabel('Colour', {exact: true}), '#123456');
    if (kind === 'project') await expectValue(retained.getByLabel('Project status'), 'paused');
    await expectValue(page.getByLabel('New label name', {exact: true}), 'Unsaved new label');
    await expectValue(page.getByLabel('New project name', {exact: true}), 'Unsaved new project');
    await expectValue(page.getByLabel('Status for the new project'), 'started');
    await expectValue(page.locator('#set-name'), 'Unsaved team name');
    // Submit the retained row too, proving its form still owns the right ID.
    await retained.getByRole('button', {name: 'Save', exact: true}).click();
    await row(`Unsaved ${kind} B`).waitFor();
    await page.reload();
    await row(`Unsaved ${kind} B`).waitFor();
    await row(`Z saved ${kind} A`).waitFor();
  }
  await page.screenshot({path: '/tmp/lll-101-settings.png'});
  return 'settings drafts survive reordered label, member and project saves';
}
