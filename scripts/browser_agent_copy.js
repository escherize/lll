// LLL-719: "Copy agent instructions" puts the /llms.txt text on the
// clipboard, scoped to the board's team and, on an issue page, to the issue.
// LLL-718 rides along: the shell's agent line is in the page but takes no
// space and is hidden from assistive technology.
//
// Driven from a signed-in session; e2e_web.sh substitutes the board URL,
// the team key and a probe issue's key.
async page => {
  const web = '__WEB__';
  const team = '__TEAM__';
  const key = '__KEY__';
  // run-code's sandbox has no URL global.
  const origin = web.replace(/^(https?:\/\/[^/]+).*$/, '$1');
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], {origin});

  const copied = async () => {
    await page.evaluate(() => navigator.clipboard.writeText('clipboard-before-click'));
    const button = page.locator('#agent-copy');
    await button.click();
    await page.waitForFunction(() => document.getElementById('agent-copy').textContent === 'Copied');
    return page.evaluate(() => navigator.clipboard.readText());
  };
  const expect = (text, part, where) => {
    if (!text.includes(part)) throw new Error(`${where}: copied text lacks ${JSON.stringify(part)}:\n${text}`);
  };

  await page.goto(`${origin}/t/${team}/`);
  const hint = page.locator('.agent-hint');
  if (await hint.getAttribute('aria-hidden') !== 'true') throw new Error('agent hint is not aria-hidden');
  const box = await hint.boundingBox();
  if (box && (box.width > 1 || box.height > 1)) throw new Error('agent hint takes space: ' + JSON.stringify(box));
  if (!(await hint.textContent()).includes('/llms.txt')) throw new Error('agent hint does not name /llms.txt');

  const onBoard = await copied();
  expect(onBoard, `# lll board at ${origin}`, 'board');
  expect(onBoard, `lll attach --key ${team}`, 'board');
  expect(onBoard, `${origin}/t/${team}/?raw`, 'board');
  if (onBoard.includes('## Your issue')) throw new Error('board copy names an issue');

  await page.goto(`${origin}/t/${team}/issue/${key}`);
  const onIssue = await copied();
  expect(onIssue, `## Your issue: ${key}`, 'issue');
  expect(onIssue, `lll issue claim ${key}`, 'issue');
  expect(onIssue, `${origin}/t/${team}/issue/${key}`, 'issue');

  // The button text comes back, so a second copy reads the same.
  await page.waitForFunction(() => document.getElementById('agent-copy').textContent === 'Copy agent instructions');
  return 'agent copy browser passed';
}
