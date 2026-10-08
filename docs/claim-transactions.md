# Claim operations

Claim acquisition and release use authenticated server operations:

| Request | JSON body | Effect |
| --- | --- | --- |
| `POST /api/lll/issues/{issue-id}/claim` | `{"member":"member-id","agent":"optional-label"}` | Acquire the exclusive claim and assign its holder in one transaction. |
| `POST /api/lll/issues/{issue-id}/release` | `{"claim_id":"observed-claim-id","agent":"","force":false,"reason":""}` | Remove that exact claim and clear assignment only if it still names the holder, in one transaction. `agent`, `force` and `reason` are optional. |
| `POST /api/lll/issues/{issue-id}/close` | `{"claim_id":"observed-claim-id or empty","agent":"","force":false,"reason":"","keep_claim":false}` | Set the issue done and release its claim under the release rule, in one transaction; the assignee is kept. `keep_claim` keeps the holder's own claim. `claim_id` is required (`""` for none); the rest are optional. |
| `POST /api/lll/issues/{issue-id}/renew` | `{"claim_id":"observed-claim-id","agent":"optional-label"}` | Restart that exact claim's expiry clock. Only the holder may renew, and a differing agent label is refused. The claim keeps its id and `created`. |
| `POST /api/lll/issues/{issue-id}/assignment` | `{"claim_id":"observed-claim-id","fields":{"assignee":"member-id"},"agent":"","force":false,"reason":""}` | Update assignment and accompanying issue fields, releasing the observed claim if assignment is cleared. `agent`, `force` and `reason` are optional and apply only to that release. |

Members can claim only for themselves; an omitted member ID uses the
authenticated member. Superusers must name the intended member. Naming the
observed claim prevents a delayed release from deleting a replacement hold.

Only the holder can release a claim without force (LLL-512). Any other caller
is refused with a message that names the holder, and the claim stays. With
`"force": true`, the release goes through and writes a comment on the issue in
the same transaction: "RELEASER force-released HOLDER's claim.", followed by
the trimmed `reason` if one was given. The releaser is the comment's author. A
superuser token names no member, so it is never the holder: it needs force like
anyone else, and its comment has no author and names "An administrator". The
response's `forced` field is true when a comment was written. The CLI spelling
is `lll issue release KEY --force [--reason "why"]`.

The expiry announcement, the one comment the server writes on its own,
carries `author_kind: "system"` (LLL-654); every other comment has `""`. No
request may set the field or edit a system comment, and a member's comment
is always authored by that member, so neither kind of record can be planted
by hand. Comments written before this are not relabelled. Only a comment's
author may edit or delete it (a superuser still moderates), and every comment
the server writes, the forced-release record included, carries
`server_record`: no request may edit it and no member may delete it. The forced-release
comment is not system: it embeds the releaser's reason, so it stays the
releaser's, attributed and labelled like any comment. Both bodies name a
member only when everyone who sees the issue's team may see that member;
otherwise they say "a member outside this team" (LLL-633).

Close releases the claim (D3, LLL-640). `lll issue close KEY` posts the hold
it observed to `/close`: the holder's close releases it and leaves no
comment, `--keep-claim` keeps it, and anyone else needs `--force` (CLI
spelling `lll issue close KEY --force [--reason "why"]`) and leaves the
forced-release comment. Only the holder may keep a claim while closing. The
assignee is kept, so a done issue still names who did it.

A claimed issue cannot be deleted (LLL-662). The issues DELETE request is
refused while a claim exists, for every caller, because the claim relation
cascades and the hold would vanish with no record. `lll issue delete KEY
--force` releases the claim first, under the release rule, then deletes. A
team deletion still cascades through its issues and claims.

A claim expires when it has not been renewed for 24 hours. The hourly sweep
ages a claim by its `updated` time, and only a renewal moves `updated`
(LLL-535). Renewing is holder-only, like a plain release: a non-holder or
superuser is refused with a message that names the holder, and the clock does
not move. Claiming your own issue again does not renew it. The CLI spelling is
`lll issue claim KEY --renew`.

The comment commits with the release, unlike the expiry announcement, which is
written after its commit. A failed expiry comment must not roll back the sweep,
or the next sweep would retry the same claim forever. A forced release has a
caller that can retry, and the comment is its only record.

Direct `DELETE /api/collections/claims/records/{id}` is superuser-only
(`claims.deleteRule` is `null`), so the holder check cannot be skipped. The
hourly expiry sweep deletes through the Go app, where collection rules do not
apply.

The board displays holders on cards and issue pages. Its **Claim as NAME**
button names the member used by the board process; the shared board login
cookie does not identify an individual member. **Release NAME's claim** submits
the claim ID rendered on that page, so an old form cannot release a replacement.
The button sends force only when the form's reason field is filled in
(LLL-662): the viewer's own claim releases without one, and anyone else's is
refused, with the refusal asking for a reason. A member login acts as that
member; the board login acts as the board's member, which the comment names,
not the person who clicked.
Archived teams show claim state without writable controls.

Claim events refresh the affected issue and team board independently of issue
events. This includes releases that preserve an unrelated assignee and therefore
do not update the issue record. New streams receive current snapshots on
connection; metadata refreshes preserve title/comment drafts and the separate
description boundary.

`lll watch` streams issue records only, so it sees a claim operation only
when the operation writes the issue. A claim that assigns its holder and a
release that clears the assignee each produce one issue update event. Claiming
an issue already assigned to you, claiming one you already hold, and renewing
produce none. `scripts/test_watch_contracts.py` pins this.

Claiming an issue already held by the same member succeeds, retains the claim
ID and creation time, and restores assignment to that member. Another member's
claim is refused. Releasing an unclaimed issue is an error. A transaction
failure rolls back the claim, assignment and comment writes.

A claim may carry an agent label (LLL-521: `--agent NAME` or `LLL_AGENT`),
stored on the hold. The same member claiming with a different non-empty label
is refused, naming the holder's label. An empty label on either side keeps the
same-member retry above. Renewal applies the same test: a session whose label
differs from the holder's cannot renew the hold. Release treats such a session
like another member: without force it is refused, naming the holder's label;
with force it goes through, and the comment names both sessions, for example
"Alpha (agent wt-b) force-released Alpha (agent wt-a)'s claim." The label is self-asserted: it separates agents
sharing one member token, not members, and proves nothing about identity.
A label is at most 64 characters from A-Z, a-z, 0-9, `.`, `_` and `-`; empty
means no label. The claim, renew and release routes, the `agent` fields and the
CLI all refuse anything else, because the label is rendered into comments.
Comments carry the same label, and every view shows it after the author.

Assignment edits must include the observed claim ID; an empty string means
the caller observed no claim. A changed observation rejects the entire edit.
While a claim exists, assigning a different member is refused. Assigning the
holder preserves the claim; assigning `""` releases it, under the same rule
as `/release` (LLL-516): the holder clears it freely; another member, a
superuser, or another agent label on the holder's token is refused naming the
holder unless the request sends `"force": true`, and a forced clear writes the
same comment a forced release writes, in the same transaction. The CLI
spelling is `lll issue update KEY --assignee none --force [--reason "why"]`.
The board's assignee editor never sends force (LLL-662): it clears only the
viewer's own hold. The optional accompanying
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
imply that arbitrary direct record edits preserve the assignment policy, with
one exception (LLL-516): a native PATCH that moves a claimed issue's assignee
to anyone but the holder is refused unless the holder's own member sends it.
PATCH carries no force and writes no comment, so everyone else, a superuser
included, clears through the assignment operation with force.

Verification lives in `gopb/claims_test.go` (real database rollback and
concurrency) and `scripts/test_claims_live.py` (authenticated HTTP, competing
CLI processes, stale releases, and older-server refusal), both run by the gate.
The decision records are `transactional-claim-operations` and
`assignment-updates-check-observed-claims` on the LLL board.
