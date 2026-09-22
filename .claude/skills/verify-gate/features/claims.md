# Claims

## Sub-features

Claiming an issue as the board's current actor, releasing it, and the board
card reflecting both. Refusal of a claim posted with a stale actor identity.

## How to get to it (user POV)

Open an issue page. The claim button names the actor it will claim as. Claim,
and the board card grows a `Claimed:` line; release, and it goes away.

## Driving it with the browser suite

`scripts/browser_claims.js`, run by `scripts/test_board_claims.py`.

It opens the issue page and a board page at once, claims, asserts the board
card updates, forges a POST with `member_id: stale-actor` and requires the
response to say `identity changed`, then releases and asserts the card detaches.

## Gotchas

**The claim is the lock, not git.** See
[parallel-work](../../parallel-work/SKILL.md). A verification run that claims an
issue on the real board is interfering with other agents - drive claims against
a scratch board only.

Claiming and releasing must not close or lose an open draft on the same page.
The driver asserts both the title draft's visibility and its value survive a
remote claim.
