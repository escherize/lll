# Attachments

## Sub-features

Attaching a file to an issue and seeing it on the issue page.

## How to get to it (user POV)

Open an issue and attach a file from the issue page.

## Driving it with the browser suite

`scripts/browser_attachments.js`, run by `scripts/test_attachments.py`.

## Gotchas

Attachments are PocketBase file fields, so a change here usually touches `pb/`.
Read [pocketbase](../../pocketbase/SKILL.md) first - collection rules where an
empty string means PUBLIC have bitten this repo before, and an attachment is
exactly the kind of record where that matters.

The visible filename and the stored record are two different assertions. Prove
both.
