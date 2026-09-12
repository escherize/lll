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

// releaseClaim names the observed hold, so a stale command or page cannot
// release a replacement claim. Assignment is checked from the fresh record
// inside this same transaction; unrelated assignment is preserved.
func releaseClaim(app core.App, issueID, expectedClaimID string) (ClaimOutcome, error) {
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
		outcome = ClaimOutcome{ClaimID: held.Id, MemberID: memberID, MemberName: name, ClearedAssignee: cleared}
		return nil
	})
	if err != nil {
		return ClaimOutcome{}, err
	}
	return outcome, nil
}
