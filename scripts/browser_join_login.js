async page => {
  // LLL-630 round 2: the two forms the board serves outside its gate must
  // still submit from a real browser, whose POST carries the page's Origin
  // only when the page's Referrer-Policy allows it.
  const confirmLink = '__CONFIRM_LINK__';
  const joinPath = '__JOIN_URL__';
  const posts = [];
  page.on('response', r => { if (r.request().method() === 'POST') posts.push(`${r.status()} ${r.url()}`); });
  // A sign-in link opened from another page (an opaque origin here) gets
  // the confirm page rather than a cookie; its button must sign in.
  await page.setContent(`<a id=go href="${confirmLink}">open</a>`);
  await page.click('#go');
  await page.getByRole('button', {name: 'Sign in'}).waitFor();
  await Promise.all([page.waitForURL(/\/t\/ALPHA\/$/), page.getByRole('button', {name: 'Sign in'}).click()]);
  if (!(await page.title()).includes('ALPHA')) throw new Error(`confirm sign-in did not land on the board: ${posts}`);
  // An invite link's name form must redeem.
  await page.context().clearCookies();
  await page.goto(joinPath);
  await page.fill('#name', 'Browser Joiner');
  await Promise.all([page.waitForURL(/\/t\/ALPHA\/$/), page.getByRole('button', {name: 'Join'}).click()]);
  if (!(await page.title()).includes('ALPHA')) throw new Error(`join did not land on the board: ${posts}`);
  if (posts.some(p => p.startsWith('403'))) throw new Error(`a same-origin form POST was refused: ${posts}`);
  return 'join and confirm passed';
}
