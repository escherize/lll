async page => {
  const base = await page.evaluate(() => location.origin);
  const key = 'ATT35-1';
  const ready = page.waitForResponse(r => r.url().includes('/events?page=issue'));
  await page.goto(`${base}/issue/${key}`);
  await ready;
  const list = page.locator('.attachment-item');
  const initial = await list.count();
  if (initial < 2) throw new Error('attachment fixtures missing');
  const comment = page.locator('#comment-form textarea');
  await comment.fill('Keep this unfinished comment');
  const input = page.locator('#attachment-upload input[type=file]');
  await input.setInputFiles('/tmp/lll-35-browser-upload.txt');
  // A real issue update must preserve both pending upload and comment draft.
  const title = `Attachment browser verification ${Date.now()}`;
  await page.request.post(`${base}/title`, {form: {key, title}});
  await page.locator('.issue-main h1').getByText(title, {exact: true}).waitFor();
  if (await input.evaluate(el => el.files.length) !== 1) throw new Error('realtime update lost selected file');
  // A rejected upload retains the selection and the comment so retry is possible.
  const issueInput = page.locator('#attachment-upload input[name=key]');
  await issueInput.evaluate(el => el.value = 'MISSING-1');
  const rejected = page.waitForResponse(r => r.url().endsWith('/attachments/upload'));
  await page.locator('#attachment-upload button').click();
  await rejected;
  await page.locator('#flash:not([hidden])').waitFor();
  if (await input.evaluate(el => el.files.length) !== 1) throw new Error('failed upload lost selected file');
  if (await comment.inputValue() !== 'Keep this unfinished comment') throw new Error('failed upload lost comment');
  await issueInput.evaluate((el, key) => el.value = key, key);
  const uploaded = page.waitForResponse(r => r.url().endsWith('/attachments/upload') && r.request().method() === 'POST');
  await page.locator('#attachment-upload button').click();
  await uploaded;
  await page.waitForFunction(n => document.querySelectorAll('.attachment-item').length === n, initial + 1);
  await page.waitForFunction(() => document.querySelector('#attachment-upload input[type=file]').files.length === 0);
  if (await comment.inputValue() !== 'Keep this unfinished comment') throw new Error('upload discarded comment draft');
  const image = page.locator('.attachment-item img').first();
  await image.scrollIntoViewIfNeeded();
  await image.evaluate(el => el.decode());
  if (await page.evaluate(() => Boolean(window.attachmentExecuted))) throw new Error('HTML attachment executed');
  const boardPage = await page.context().newPage();
  const boardReady = boardPage.waitForResponse(r => r.url().includes('/events'));
  await boardPage.goto(`${base}/t/ATT35/`);
  await boardReady;
  const card = boardPage.locator('.card').filter({hasText: key});
  const badge = card.locator('.attachment-count');
  if (Number(await badge.innerText()) !== initial + 1) throw new Error('card count incorrect');
  if (await card.locator('img').count()) throw new Error('board loaded attachment image');
  // Real remove action updates both open surfaces and preserves the draft.
  const remove = list.last().getByRole('button', {name: /^Remove /});
  // The CLI browser driver yields at native dialogs; the manual probe also
  // exercised native acceptance. Keep this automated state test deterministic.
  await page.evaluate(() => window.confirm = () => true);
  await remove.click();
  await page.waitForFunction(n => document.querySelectorAll('.attachment-item').length === n, initial);
  await boardPage.waitForFunction(n => Number(document.querySelector('.attachment-count').textContent) === n, initial);
  if (await comment.inputValue() !== 'Keep this unfinished comment') throw new Error('removal discarded comment');
  for (const width of [1280, 390]) {
    await page.setViewportSize({width, height: 900});
    await page.locator('.issue-attachments').scrollIntoViewIfNeeded();
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error(`page overflow at ${width}`);
    await page.screenshot({path: `/tmp/lll-35-attachments-${width}.png`});
  }
  await boardPage.close();
  return 'Attachment browser passed';
}
