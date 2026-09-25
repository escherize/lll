// LLL-531/532: '?' sheet, '/' to board search, and g-chords to rail rows.
// Every negative here is a keypress that must NOT act: a shortcut that eats
// a letter meant for a field is worse than no shortcut at all.
//
// e2e_web.sh substitutes the base URL.
async page => {
  const base = '__WEB__';
  // run-code has no URL global, so the page reports its own path.
  const path = () => page.evaluate(() => location.pathname);

  await page.goto(base + '/');
  // The board may redirect to its team (/t/ENG/); every 'stayed put' check
  // compares against where it actually landed.
  const home = await path();
  await page.keyboard.press('?');
  await page.locator('#kbd-help[open]').waitFor();
  await page.keyboard.press('Escape');
  await page.locator('#kbd-help').waitFor({state: 'hidden'});

  await page.keyboard.press('/');
  await page.waitForFunction(() => document.activeElement?.id === 'board-search-input');
  // Inside a field a chord is text: it stays in the field and goes nowhere.
  await page.keyboard.type('gi', {delay: 40});
  await page.waitForTimeout(300);
  if (await path() !== home) throw new Error('a chord typed into search navigated to ' + await path());
  if (await page.inputValue('#board-search-input') !== 'gi') throw new Error('search field lost the typed chord');
  await page.keyboard.press('Escape');
  await page.evaluate(() => document.activeElement.blur());

  // The new-issue form is a Datastar-shown div, not a <dialog>. With focus
  // off its fields, a chord over it once navigated away and lost the draft.
  await page.keyboard.press('c');
  await page.locator('#ni-title').fill('draft a chord must not lose');
  await page.locator('#ni-form .ni-head').click();
  await page.keyboard.press('g');
  await page.keyboard.press('i');
  await page.waitForTimeout(500);
  if (await path() !== home) throw new Error('a chord over the new-issue form navigated to ' + await path());
  await page.keyboard.press('Escape');
  await page.locator('#ni-form').waitFor({state: 'hidden'});

  await page.keyboard.press('g');
  await page.keyboard.press('i');
  await page.waitForURL(/\/issues$/);
  // /issues loads no Datastar: the sheet and chords are navigation.js alone.
  await page.keyboard.press('?');
  await page.locator('#kbd-help[open]').waitFor();
  await page.keyboard.press('Escape');
  await page.keyboard.press('g');
  await page.keyboard.press('p');
  await page.waitForURL(/\/projects$/);
  await page.keyboard.press('g');
  await page.keyboard.press('b');
  await page.waitForFunction(h => location.pathname === h, home);

  // A chord older than a second has expired: the second key is just a key.
  await page.keyboard.press('g');
  await page.waitForTimeout(1300);
  await page.keyboard.press('i');
  await page.waitForTimeout(500);
  if (await path() !== home) throw new Error('an expired chord still navigated to ' + await path());
  return 'keyboard shortcuts browser passed';
}
