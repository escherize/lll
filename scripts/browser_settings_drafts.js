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
    // The nav is the section's sibling, not part of the morph: a save must
    // not take it with it.
    await page.locator(`#set-nav a.active`).waitFor();
  }
  await page.screenshot({path: '/tmp/lll-101-settings.png'});
  return 'settings drafts survive reordered label, member and project saves';
}
