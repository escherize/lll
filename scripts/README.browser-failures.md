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
`text/event-stream`; the visible `#flash` error is the application result.
A 200 status alone does not prove a successful write.

Check the visible flash, the create dialog's open state and retained title
and description, and unchanged stored data through the CLI or a reload.
Distinguish a locally selected control value from the stored value: inspect
both rather than treating the browser selection as proof of persistence.
The state probe records the selection at failure as well as after reload.

Remove the field in a `finally` block, or reload the page, before continuing:

```js
await page.locator('[data-failure-probe]').evaluateAll(fields => {
  fields.forEach(field => field.remove());
});
```

The gate takes screenshots at `/tmp/lll-131-create.png` and
`/tmp/lll-131-state.png`. It checks the rendered failure and persisted data;
there is no application failure flag to leave enabled accidentally.

Observed follow-ups: LLL-348 tracks a rejected state selection remaining
visible until reload; LLL-349 tracks create errors rendering behind the modal
shade. The probes make these defects reproducible. A passing retention or
persistence assertion does not prove that the failure UI is fully usable;
inspect the screenshots as well.
