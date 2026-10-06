package gopb

import (
	"database/sql"
	"errors"
	"fmt"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/core"
)

// ClaimOutcome is the committed domain transition, shared by HTTP adapters.
// The caller must authenticate the actor before acquiring a claim.
type ClaimOutcome struct {
	ClaimID         string `json:"claim_id"`
	MemberID        string `json:"member_id"`
	MemberName      string `json:"member_name"`
	Created         string `json:"created"`
	AlreadyOwned    bool   `json:"already_owned"`
	ClearedAssignee bool   `json:"cleared_assignee"`
	// Forced is true when the release took another member's claim and left a
	// comment saying so (LLL-512).
	Forced bool `json:"forced"`
}

type claimRejection struct{ message string }

func (e *claimRejection) Error() string { return e.message }

func currentClaim(app core.App, issueID string) (*core.Record, error) {
	claim, err := app.FindFirstRecordByFilter("claims", "issue={:issue}", dbx.Params{"issue": issueID})
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	return claim, err
}

// acquireClaim keeps both the exclusive hold and its assignment on the
// serialized writer transaction. A duplicate by its holder repairs assignment
// without replacing the original claim or its creation time.
func acquireClaim(app core.App, issueID, memberID string) (ClaimOutcome, error) {
	var outcome ClaimOutcome
	err := app.RunInTransaction(func(tx core.App) error {
		issue, err := tx.FindRecordById("issues", issueID)
		if err != nil {
			return err
		}
		member, err := tx.FindRecordById("members", memberID)
		if err != nil {
			return err
		}
		held, err := currentClaim(tx, issueID)
		if err != nil {
			return err
		}
		alreadyOwned := held != nil
		if held != nil && held.GetString("member") != memberID {
			name := "someone else"
			if holder, err := tx.FindRecordById("members", held.GetString("member")); err == nil {
				name = holder.GetString("name")
			}
			return &claimRejection{fmt.Sprintf("issue is already claimed by %s", name)}
		}
		if held == nil {
			collection, err := tx.FindCollectionByNameOrId("claims")
			if err != nil {
				return err
			}
			held = core.NewRecord(collection)
			held.Set("issue", issueID)
			held.Set("member", memberID)
			if err := tx.Save(held); err != nil {
				return err
			}
		}
		if issue.GetString("assignee") != memberID {
			issue.Set("assignee", memberID)
			if err := tx.Save(issue); err != nil {
				return err
			}
		}
		outcome = ClaimOutcome{ClaimID: held.Id, MemberID: memberID, MemberName: member.GetString("name"),
			Created: held.GetString("created"), AlreadyOwned: alreadyOwned}
		return nil
	})
	if err != nil {
		return ClaimOutcome{}, err
	}
	return outcome, nil
}

// releaser is who asked for a release, as the HTTP adapter authenticated it.
// memberID is empty for a superuser: that token names no member, so it can
// never be the holder and always needs force.
type releaser struct {
	memberID string
	force    bool
	reason   string
}

// releaseClaim names the observed hold, so a stale command or page cannot
// release a replacement claim. Assignment is checked from the fresh record
// inside this same transaction; unrelated assignment is preserved.
//
// Only the holder releases without force (LLL-512): in a fleet, a confused
// sibling releasing someone else's hold unlocks an issue another agent is
// still editing. The holder is read from the fresh record inside the
// transaction, so the check and the delete see the same claim.
func releaseClaim(app core.App, issueID, expectedClaimID string, by releaser) (ClaimOutcome, error) {
	var outcome ClaimOutcome
	err := app.RunInTransaction(func(tx core.App) error {
		issue, err := tx.FindRecordById("issues", issueID)
		if err != nil {
			return err
		}
		held, err := currentClaim(tx, issueID)
		if err != nil {
			return err
		}
		if held == nil {
			return &claimRejection{"is not claimed"}
		}
		if expectedClaimID == "" || held.Id != expectedClaimID {
			return &claimRejection{"the claim changed; refresh before releasing it"}
		}
		memberID := held.GetString("member")
		name := "an unknown member"
		if member, err := tx.FindRecordById("members", memberID); err == nil {
			name = member.GetString("name")
		}
		forced := memberID != by.memberID
		if forced && !by.force {
			return &claimRejection{fmt.Sprintf("the claim is held by %s; releasing another member's claim needs force", name)}
		}
		cleared := issue.GetString("assignee") == memberID
		if err := tx.Delete(held); err != nil {
			return err
		}
		if cleared {
			issue.Set("assignee", "")
			if err := tx.Save(issue); err != nil {
				return err
			}
		}
		if forced {
			if err := recordForcedRelease(tx, issueID, name, by); err != nil {
				return err
			}
		}
		outcome = ClaimOutcome{ClaimID: held.Id, MemberID: memberID, MemberName: name, ClearedAssignee: cleared, Forced: forced}
		return nil
	})
	if err != nil {
		return ClaimOutcome{}, err
	}
	return outcome, nil
}

// recordForcedRelease writes the comment a forced release owes the holder
// (LLL-512). It runs INSIDE the release transaction, the opposite of the
// expiry announcement (LLL-452), and for the reason LLL-452 gave: that comment
// goes after the commit because rolling back an unattended sweep over a comment
// would hand the same claim to the next sweep forever. Here a person or agent
// is waiting on the answer and can retry, and the comment is the price of
// force, not a courtesy - a forced release with no record is the silent
// release this issue exists to stop.
//
// The releaser is the author, so the comment is attributed like any other. A
// superuser has no member record and the comment goes authorless, which the
// web renders as "anon"; the body names the actor either way.
func recordForcedRelease(tx core.App, issueID, holder string, by releaser) error {
	actor := "An administrator"
	if by.memberID != "" {
		member, err := tx.FindRecordById("members", by.memberID)
		if err != nil {
			return err
		}
		actor = member.GetString("name")
	}
	body := fmt.Sprintf("%s force-released %s's claim.", actor, holder)
	if by.reason != "" {
		body += "\n\nReason: " + by.reason
	}
	comments, err := tx.FindCollectionByNameOrId("comments")
	if err != nil {
		return err
	}
	comment := core.NewRecord(comments)
	comment.Set("issue", issueID)
	comment.Set("author", by.memberID)
	comment.Set("body", body)
	return tx.Save(comment)
}

// renewClaim restarts a hold's expiry clock (LLL-535). The sweep ages a claim
// by `updated`, and nothing but this writes a claim, so saving it unchanged is
// the renewal: the autodate moves and the claim keeps its id and `created`.
// Keeping the id matters - release and assignment name the observed claim_id,
// so a delete-and-recreate would turn every open page's next release into
// "the claim changed".
//
// Only the holder renews, and only the hold it observed: renewing is a promise
// that the work is still alive, which no one else can make.
func renewClaim(app core.App, issueID, expectedClaimID, memberID string) (ClaimOutcome, error) {
	var outcome ClaimOutcome
	err := app.RunInTransaction(func(tx core.App) error {
		held, err := currentClaim(tx, issueID)
		if err != nil {
			return err
		}
		if held == nil {
			return &claimRejection{"is not claimed"}
		}
		if expectedClaimID == "" || held.Id != expectedClaimID {
			return &claimRejection{"the claim changed; refresh before renewing it"}
		}
		holderID := held.GetString("member")
		name := "an unknown member"
		if member, err := tx.FindRecordById("members", holderID); err == nil {
			name = member.GetString("name")
		}
		if holderID != memberID {
			return &claimRejection{fmt.Sprintf("the claim is held by %s; only the holder renews it", name)}
		}
		if err := tx.Save(held); err != nil {
			return err
		}
		outcome = ClaimOutcome{ClaimID: held.Id, MemberID: holderID, MemberName: name, Created: held.GetString("created")}
		return nil
	})
	if err != nil {
		return ClaimOutcome{}, err
	}
	return outcome, nil
}
