// LLL-101: saving one row must not discard the drafts typed into its
// neighbours, including when the save reorders the list.
//
// LLL-446: each kind has its own section now, so the run navigates to each
// one. The cross-section half of the old assertion (a team-name draft
// surviving a label save) is gone with the page that had both on it: a save
// answers with its own section, and the other sections are not on screen to
// lose anything. What is left is the property that still exists — drafts
// within the section being written survive the write.
async page => {
  const section = name => page.url().replace(/\/settings\/[^/?#]*.*$/, '/settings/' + name);
  for (const [kind, plural] of [['label', 'labels'], ['member', 'members'], ['project', 'projects']]) {
    await page.goto(section(plural));
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
    const newName = {label: 'New label name', member: 'New member name', project: 'New project name'}[kind];
    await page.getByLabel(newName, {exact: true}).fill(`Unsaved new ${kind}`);
    if (kind === 'project') await page.getByLabel('Status for the new project').selectOption('started');
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
    await expectValue(page.getByLabel(newName, {exact: true}), `Unsaved new ${kind}`);
    if (kind === 'project') await expectValue(page.getByLabel('Status for the new project'), 'started');
    // Submit the retained row too, proving its form still owns the right ID.
    await retained.getByRole('button', {name: 'Save', exact: true}).click();
    await row(`Unsaved ${kind} B`).waitFor();
    await page.reload();
    await row(`Unsaved ${kind} B`).waitFor();
    await row(`Z saved ${kind} A`).waitFor();
    if (kind === 'label' || kind === 'project') {
      const invalid = row(`Z saved ${kind} A`);
      const peer = row(`Unsaved ${kind} B`).locator('input[name="name"]');
      await invalid.locator('input[name="name"]').fill(`Invalid, ${kind}`);
      await peer.fill(`Unsubmitted ${kind} draft`);
      await page.getByLabel(newName, {exact: true}).fill(`Unsubmitted new ${kind}`);
      const rejected = async button => {
        const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/settings/' + kind));
        await button.click();
        const body = await (await response).text();
        if (!body.includes('names cannot contain commas')) throw new Error('missing comma refusal');
        await page.locator('#flash').getByText('names cannot contain commas', {exact: false}).waitFor();
      };
      await rejected(invalid.getByRole('button', {name: 'Save', exact: true}));
      await expectValue(invalid.locator('input[name="name"]'), `Invalid, ${kind}`);
      await expectValue(peer, `Unsubmitted ${kind} draft`);
      await expectValue(page.getByLabel(newName, {exact: true}), `Unsubmitted new ${kind}`);
      const viewport = page.viewportSize();
      await page.screenshot({path: `/tmp/lll-524-${kind}-desktop.png`});
      await page.setViewportSize({width: 390, height: 844});
      await page.screenshot({path: `/tmp/lll-524-${kind}-mobile.png`});
      await page.setViewportSize(viewport);
      await page.getByLabel(newName, {exact: true}).fill(`Invalid, new ${kind}`);
      await rejected(page.getByRole('button', {name: 'Add ' + kind, exact: true}));
      await expectValue(page.getByLabel(newName, {exact: true}), `Invalid, new ${kind}`);
      await page.reload();
      await row(`Z saved ${kind} A`).waitFor();
      await row(`Unsaved ${kind} B`).waitFor();
    }
    const viewport = page.viewportSize();
    for (const width of [390, 320]) {
      await page.setViewportSize({width, height: 844});
      const geometry = await row(`Z saved ${kind} A`).evaluate(el => {
        const row = el.getBoundingClientRect();
        const name = el.querySelector('input[name="name"]').getBoundingClientRect();
        const controls = [...el.querySelectorAll('input:not([type="hidden"]), select, button')];
        return {nameWidth: name.width, rowWidth: row.width,
          fits: controls.every(control => { const r = control.getBoundingClientRect();
            return r.left >= row.left && r.right <= row.right; })};
      });
      if (geometry.nameWidth < geometry.rowWidth - 54 || !geometry.fits)
        throw new Error(`${kind} settings fields cramped at ${width}px: ${JSON.stringify(geometry)}`);
      await page.screenshot({path: `/tmp/lll-559-${kind}-${width}.png`});
    }
    await page.setViewportSize(viewport);

    // The nav is the section's sibling, not part of the morph: a save must
    // not take it with it.
    await page.locator(`#set-nav a.active`).waitFor();
  }
  const viewport = page.viewportSize();
  for (const width of [390, 320]) {
    await page.setViewportSize({width, height: 844});
    const nav = page.getByRole('navigation', {name: 'Settings sections'});
    const layout = await nav.evaluate(el => ({width: el.clientWidth, parent: el.parentElement.clientWidth}));
    if (Math.abs(layout.width - layout.parent) > 1) throw new Error(`settings nav clipped at ${width}px`);
    for (const name of ['Identity', 'Labels', 'Projects', 'Teams', 'Members', 'Access']) {
      const link = nav.getByRole('link', {name, exact: true});
      await link.scrollIntoViewIfNeeded();
      const fits = await link.evaluate(el => {
        const r = el.getBoundingClientRect(), n = el.closest('nav').getBoundingClientRect();
        return r.left >= n.left - 1 && r.right <= n.right + 1 && r.width + 1 >= el.scrollWidth;
      });
      if (!fits) throw new Error(`settings link ${name} clipped at ${width}px`);
    }
    await nav.locator('a.active').scrollIntoViewIfNeeded();
    await page.screenshot({path: `/tmp/lll-558-settings-${width}.png`});
  }
  await page.setViewportSize(viewport);
  const previous = page.url();
  await page.getByRole('navigation', {name: 'Settings sections'}).getByRole('link', {name: /^Access/}).click();
  const longMember = 'A long agent member name that needs to stay inside a narrow settings form';
  for (const selector of ['#access-token-form', '#access-credential-form']) {
    await page.locator(selector + ' select').selectOption({label: longMember});
  }
  for (const width of [320, 390]) {
    await page.setViewportSize({width, height: 844});
    const fits = await page.locator('#access').evaluate(section => {
      const bounds = section.getBoundingClientRect();
      return bounds.right <= innerWidth && [...section.querySelectorAll('input, select, button')].every(el => {
        const r = el.getBoundingClientRect();
        return r.left >= bounds.left && r.right <= bounds.right + 1;
      });
    });
    if (!fits) throw new Error(`Access settings controls clipped at ${width}px`);
    await page.screenshot({path: `/tmp/lll-568-access-${width}.png`});
  }
  await page.setViewportSize(viewport);
  await page.goto(previous);
  await page.screenshot({path: '/tmp/lll-101-settings.png'});
  return 'settings drafts survive reordered label, member and project saves';
}
