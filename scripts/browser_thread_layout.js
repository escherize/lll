// LLL-424: Related findings and Comments are two .thread sections, and a
// named grid area places EVERY element that claims it in the same cell - so
// an issue carrying both drew one on top of the other, in both layouts, with
// a DOM that was entirely correct. Only geometry can see that, which is why
// this is a browser check and not an assertion about markup.
async page => {
  const origin = await page.evaluate(() => location.origin);
  const boxes = async () => await page.evaluate(() => {
    const rect = (sel) => {
      const el = document.querySelector(sel);
      if (!el) throw new Error('missing section: ' + sel);
      const r = el.getBoundingClientRect();
      return {top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height)};
    };
    return {findings: rect('#related-findings'), comments: rect('#comments')};
  });
  // Both layouts: the wide grid and the phone one, which names its rows
  // separately and so can regress on its own.
  for (const [width, height] of [[1280, 800], [390, 844]]) {
    await page.setViewportSize({width, height});
    await page.goto(origin + '/issue/ENG-1');
    const {findings, comments} = await boxes();
    if (findings.height < 1 || comments.height < 1) {
      throw new Error(`${width}px: a section has no height: ` + JSON.stringify({findings, comments}));
    }
    // Not merely "different": they must not overlap at all.
    if (findings.bottom > comments.top) {
      throw new Error(`${width}px: findings and comments overlap: ` + JSON.stringify({findings, comments}));
    }
  }
  await page.setViewportSize({width: 1280, height: 800});
  return 'thread sections stack without overlapping';
}
