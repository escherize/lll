# Drafts and forms

## Sub-features

Drafts surviving a broadcast that repaints the page around them. The
create-more dialog keeping its state through back-to-back creates. Server-side
validation, with a refused create or state change explaining itself rather than
failing silently.

## How to get to it (user POV)

Start typing a comment or a title, and have something else change on the board.
Your text stays. Create an issue with the create-more dialog and create another
immediately - the dialog keeps its state.

## Driving it with the browser suite

`scripts/browser_settings_drafts.js`, `scripts/browser_create_failure.js`, and
`scripts/browser_state_failure.js`, all run inline in `e2e_web.sh`.

## Gotchas

This is the most common place for a fragment-ownership regression to land. A
broadcast that clears a draft passes every CLI test and fails the user. Read
[datastar-fragments](../../datastar-fragments/SKILL.md) first.

A failed create must say why. `-f` on a curl throws the body away, which is how
a refusal once got reported as a missing feature several assertions later.
