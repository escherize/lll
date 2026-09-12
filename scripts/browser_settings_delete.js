async page => {
  const form = page.locator('form.set-row').filter({
    has: page.locator('input[name="name"][value="Deletion browser project"]')
  });
  const id = await form.getAttribute('id');
  const row = page.locator('#' + id);
  await row.getByRole('button', {name: 'Delete', exact: true}).click();
  await row.getByText('This removes the project from 1 issue(s).', {exact: false}).waitFor();
  await row.getByRole('button', {name: 'Cancel', exact: true}).click();
  await row.locator('input[name="name"]').waitFor();
  await row.getByRole('button', {name: 'Delete', exact: true}).click();
  await row.getByRole('button', {name: 'Delete project', exact: true}).waitFor();
  await row.scrollIntoViewIfNeeded();
  await page.screenshot({path: '/tmp/lll-233-delete-review.png'});
  await row.getByRole('button', {name: 'Delete project', exact: true}).click();
  await row.waitFor({state: 'detached'});
  return 'settings deletion browser passed';
}
