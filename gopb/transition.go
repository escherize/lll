package gopb

import "github.com/pocketbase/pocketbase/core"

// The transition table (LLL-685): what changing an issue's state does to
// its claim. src/models/transition.lis is the same table in Lisette, the rule
// the CLI and the board plan their writes and report outcomes by. This copy
// is the server's, because the hooks and routes that enforce it run here, in
// the transaction that saves the issue. src/models/transition.test.lis runs
// every row through both copies and fails when they disagree.
//
// A state change never edits the assignee: a finished issue keeps it as the
// record of who did the work (fleet case 07). Only an assignee edit
// (/assignment) clears it.

// Who holds the issue's claim, from the caller's side. A superuser has no
// member, so every hold is another member's to it.
const (
	HoldNone         = "none"
	HoldCaller       = "caller"
	HoldOtherSession = "other-session"
	HoldOtherMember  = "other-member"
)

// How the state change was asked for: /close, or any other write that sets
// the state (/assignment, a native PATCH).
const (
	VerbClose = "close"
	VerbMove  = "move"
)

// What the change does to the claim.
const (
	// ClaimUntouched: no hold, or a move that is not a finish.
	ClaimUntouched = "untouched"
	// ClaimReleased: the holder's own finish gives the hold back.
	ClaimReleased = "released"
	// ClaimKept: the holder finished and kept the hold (keep_claim).
	ClaimKept = "kept"
	// ClaimForceReleased: a forced close took another's hold; it owes the
	// forced-release comment.
	ClaimForceReleased = "force-released"
	// ClaimLeft: a move by anyone but the holder leaves the hold alone. A
	// PATCH carries no force and writes no comment.
	ClaimLeft = "left"
)

// TransitionClaim is the table. from and to are state wire values; for
// VerbClose to is "done" and from is not consulted, because closing settles
// the hold whatever the issue was. refusal is "" or the claimRejection code
// the write is refused with: needs_force for a close over another's hold
// without force, claim_held for keeping another's hold. Exported so the
// Lisette test can pin both copies on one table.
func TransitionClaim(verb, from, to, hold string, keepClaim, force bool) (effect, refusal string) {
	if hold == HoldNone {
		return ClaimUntouched, ""
	}
	mine := hold == HoldCaller
	if verb == VerbClose {
		switch {
		case !mine && !force:
			return "", "needs_force"
		case !mine && keepClaim:
			return "", "claim_held"
		case !mine:
			return ClaimForceReleased, ""
		case keepClaim:
			return ClaimKept, ""
		default:
			return ClaimReleased, ""
		}
	}
	if from == to || (to != "done" && to != "cancelled") {
		return ClaimUntouched, ""
	}
	switch {
	case !mine:
		return ClaimLeft, ""
	case keepClaim:
		return ClaimKept, ""
	default:
		return ClaimReleased, ""
	}
}

// holdOf names held from by's side. The same member under a different
// non-empty agent label is another session (LLL-521).
func holdOf(held *core.Record, by releaser) string {
	switch {
	case held == nil:
		return HoldNone
	case by.memberID == "" || held.GetString("member") != by.memberID:
		return HoldOtherMember
	case agentsDiffer(held, by.agent):
		return HoldOtherSession
	default:
		return HoldCaller
	}
}
