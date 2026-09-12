# Claim operations

Claim acquisition and release use authenticated server operations:

| Request | JSON body | Effect |
| --- | --- | --- |
| `POST /api/lll/issues/{issue-id}/claim` | `{"member":"member-id"}` | Acquire the exclusive claim and assign its holder in one transaction. |
| `POST /api/lll/issues/{issue-id}/release` | `{"claim_id":"observed-claim-id"}` | Remove that exact claim and clear assignment only if it still names the holder, in one transaction. |
| `POST /api/lll/issues/{issue-id}/assignment` | `{"claim_id":"observed-claim-id","fields":{"assignee":"member-id"}}` | Update assignment and accompanying issue fields, releasing the observed claim if assignment is cleared. |

Members can claim only for themselves; an omitted member ID uses the
authenticated member. Superusers must name the intended member. Any
authenticated workspace member can release a hold. Naming the observed claim
prevents a delayed release from deleting a replacement hold.

The board displays holders on cards and issue pages. Its **Claim as NAME**
button names the member used by the board process; the shared board login
cookie does not identify an individual member. **Release NAME's claim** submits
the claim ID rendered on that page, so an old form cannot release a replacement.
Archived teams show claim state without writable controls.

Claim events refresh the affected issue and team board independently of issue
events. This includes releases that preserve an unrelated assignee and therefore
do not update the issue record. New streams receive current snapshots on
connection; metadata refreshes preserve title/comment drafts and the separate
description boundary.

Claiming an issue already held by the same member succeeds, retains the claim
ID and creation time, and restores assignment to that member. Another member's
claim is refused. Releasing an unclaimed issue is an error. A transaction
failure rolls back both the claim and assignment writes.

Assignment edits must include the observed claim ID; an empty string means
the caller observed no claim. A changed observation rejects the entire edit.
While a claim exists, assigning a different member is refused. Assigning the
holder preserves the claim; assigning `""` releases it. The optional accompanying
fields are `title`, `description`, `state`, `priority`, `emoji`, `project`, and
`labels`. Omitted fields stay unchanged; explicit empty values and zero priority
are applied. Field validation and claim release belong to the same transaction,
so a bad title or failed deletion does not leave a partially applied edit.

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
claim and assignment changes automatically. CLI `issue update --assignee ...`
and the board's assignee editor use the assignment operation. Edits without
assignment continue to use native PATCH. This transaction contract does not
imply that arbitrary direct record edits preserve the assignment policy.

Verification lives in `gopb/claims_test.go` (real database rollback and
concurrency) and `scripts/test_claims_live.py` (authenticated HTTP, competing
CLI processes, stale releases, and older-server refusal), both run by the gate.
The decision records are `transactional-claim-operations` and
`assignment-updates-check-observed-claims` on the LLL board.
