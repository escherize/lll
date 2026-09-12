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
  const memberForm = page.locator('form.set-row').filter({
    has: page.locator('input[name="name"][value="Deletion browser member"]')
  });
  const memberRow = page.locator('#' + await memberForm.getAttribute('id'));
  await memberRow.getByRole('button', {name: 'Delete', exact: true}).click();
  await memberRow.getByText('This clears 1 issue assignment(s) and 0 comment author reference(s).', {exact: false}).waitFor();
  await memberRow.getByRole('button', {name: 'Cancel', exact: true}).click();
  await memberRow.locator('input[name="name"]').waitFor();
  await memberRow.getByRole('button', {name: 'Delete', exact: true}).click();
  await memberRow.getByLabel('Admin password', {exact: true}).fill('wrong-admin-password');
  await memberRow.getByRole('button', {name: 'Delete account', exact: true}).click();
  await page.locator('#flash').getByText('wrong admin password', {exact: false}).waitFor();
  await memberRow.getByLabel('Admin password', {exact: true}).fill('');
  await memberRow.scrollIntoViewIfNeeded();
  await page.screenshot({path: '/tmp/lll-341-delete-review.png'});
  // The web harness pins these throwaway credentials in scripts/lib.sh.
  await memberRow.getByLabel('Admin password', {exact: true}).fill('admin-local-123');
  await memberRow.getByRole('button', {name: 'Delete account', exact: true}).click();
  await memberRow.waitFor({state: 'detached'});
  return 'settings deletion browser passed; member admin deletion passed';
}
