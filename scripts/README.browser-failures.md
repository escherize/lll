# Exercising browser action failures

Run `mise run gate` for the isolated CLI/browser suite. The create failure
probe is in `e2e_web.sh`; `browser_state_failure.js` exercises the issue
state form. Both submit through the actual Datastar event handler and use
the actual server's validation and flash response.

For a manual reproduction, start `mise run scratch -- --no-open`, open its
printed board login URL, and use only that throwaway board. In Playwright,
open the create dialog with a title and description, or open a scratch
issue's detail page. Temporarily prepend this field to `#ni-form` or
`#state-form`:

```js
await page.locator('#state-form').evaluate(form => {
  const field = document.createElement('input');
  field.type = 'hidden';
  field.name = 'state';
  field.value = 'bogus';
  field.dataset.failureProbe = 'true';
  form.prepend(field);
});
```

Click Create, or select a different valid state in the issue form. Go's
`FormValue` reads the first submitted `state`, so the added field makes the
normal handler reject the request. The HTTP response is still 200 with
`text/event-stream`; the visible alert is the application result: `#ni-flash`
inside the create dialog, or `#flash` for issue-page actions.
A 200 status alone does not prove a successful write.

Check the visible flash, the create dialog's open state and retained title
and description, and unchanged stored data through the CLI or a reload.
Distinguish a locally selected control value from the stored value: inspect
both rather than treating the browser selection as proof of persistence.
The property probe checks that state, priority, assignee, project and label
controls return to current server values without a reload. It also checks
that an unsaved comment survives recovery. If refreshing the values fails,
the Properties panel reports that they could not be verified and offers a
reload; it does not leave the rejected selection looking current.

Remove the field in a `finally` block, or reload the page, before continuing:

```js
await page.locator('[data-failure-probe]').evaluateAll(fields => {
  fields.forEach(field => field.remove());
});
```

The gate takes screenshots at `/tmp/lll-131-create.png` and
`/tmp/lll-131-state.png`. It checks the rendered failure and persisted data;
there is no application failure flag to leave enabled accidentally.

LLL-348 added server-backed property recovery after rejected writes.
LLL-349 moved create errors inside the dialog. `browser_create_failure.js`
checks the alert semantics, form description relationship, desktop/mobile
hit testing, keyboard retry with retained drafts, and clearing on fresh open.
Its screenshots are `/tmp/lll-349-create-1280.png` and
`/tmp/lll-349-create-390.png`. These checks verify markup and browser behavior;
they do not substitute for testing speech output with a screen reader.
