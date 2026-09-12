# Claim operations

Claim acquisition and release use authenticated server operations:

| Request | JSON body | Effect |
| --- | --- | --- |
| `POST /api/lll/issues/{issue-id}/claim` | `{"member":"member-id"}` | Acquire the exclusive claim and assign its holder in one transaction. |
| `POST /api/lll/issues/{issue-id}/release` | `{"claim_id":"observed-claim-id"}` | Remove that exact claim and clear assignment only if it still names the holder, in one transaction. |

Members can claim only for themselves; an omitted member ID uses the
authenticated member. Superusers must name the intended member. Any
authenticated workspace member can release a hold. Naming the observed claim
prevents a delayed release from deleting a replacement hold.

Claiming an issue already held by the same member succeeds, retains the claim
ID and creation time, and restores assignment to that member. Another member's
claim is refused. Releasing an unclaimed issue is an error. A transaction
failure rolls back both the claim and assignment writes.

The response describes the committed transition: `claim_id`, `member_id`,
`member_name`, `created`, `already_owned`, and `cleared_assignee`. Consumers
share the Lisette `claims` module rather than assembling separate record
writes. Issue request locking also coordinates these operations with native
issue PATCH and DELETE requests.

Deploy the updated server before distributing a client using these routes.
An older server returns 404; the CLI explains that a server upgrade is needed
and makes no fallback claim-record writes. If a connection drops after commit,
the client cannot know the result: inspect the issue or retry acquisition,
which is idempotent for the holder. A repeated release reports that the hold
is gone or has changed.

Native PocketBase record CRUD is a lower-level interface and does not compose
claim and assignment changes automatically. The separate assignment-update
policy (`issue update --assignee ...`) is tracked in LLL-358. This transaction
contract does not imply that arbitrary direct record edits preserve that
policy.

Verification lives in `gopb/claims_test.go` (real database rollback and
concurrency) and `scripts/test_claims_live.py` (authenticated HTTP, competing
CLI processes, stale releases, and older-server refusal), both run by the gate.
The decision record is `transactional-claim-operations` on the LLL board.
