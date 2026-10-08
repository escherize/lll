package gopb

import (
	"bytes"
	"encoding/json"
	"fmt"

	"github.com/pocketbase/pocketbase/core"
)

// Only issue-editor fields cross this boundary. Pointer fields distinguish an
// omitted edit from an explicit zero/empty value; PocketBase validates values
// and relations when saving the complete record.
type assignmentFields struct {
	Assignee    *string   `json:"assignee"`
	Title       *string   `json:"title"`
	Description *string   `json:"description"`
	State       *string   `json:"state"`
	Priority    *int      `json:"priority"`
	Emoji       *string   `json:"emoji"`
	Project     *string   `json:"project"`
	Labels      *[]string `json:"labels"`
	// LLL-513: 'lll issue update --add-label/--remove-label' combined with
	// --assignee arrives here. Set resolves the modifier against the issue
	// read inside the transaction.
	LabelsAdd    *[]string `json:"labels+"`
	LabelsRemove *[]string `json:"labels-"`
}

func parseAssignmentFields(raw json.RawMessage) (assignmentFields, error) {
	var fields assignmentFields
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&fields); err != nil {
		return fields, err
	}
	if fields.Assignee == nil {
		return fields, fmt.Errorf("assignment update requires an assignee")
	}
	return fields, nil
}

// refsInScope applies the scoped-reference rule (team_scope.go) to the
// project and labels this update would set or add.
func (fields assignmentFields) refsInScope(re *core.RequestEvent) error {
	if re.Auth == nil {
		return nil
	}
	var labels []string
	if fields.Labels != nil {
		labels = append(labels, *fields.Labels...)
	}
	if fields.LabelsAdd != nil {
		labels = append(labels, *fields.LabelsAdd...)
	}
	if err := refsInScope(re.App, re.Auth, "labels", labels); err != nil {
		return err
	}
	if fields.Project != nil && *fields.Project != "" {
		return refsInScope(re.App, re.Auth, "projects", []string{*fields.Project})
	}
	return nil
}

func (fields assignmentFields) apply(issue *core.Record) {
	issue.Set("assignee", *fields.Assignee)
	if fields.Title != nil {
		issue.Set("title", *fields.Title)
	}
	if fields.Description != nil {
		issue.Set("description", *fields.Description)
	}
	if fields.State != nil {
		issue.Set("state", *fields.State)
	}
	if fields.Priority != nil {
		issue.Set("priority", *fields.Priority)
	}
	if fields.Emoji != nil {
		issue.Set("emoji", *fields.Emoji)
	}
	if fields.Project != nil {
		issue.Set("project", *fields.Project)
	}
	if fields.Labels != nil {
		issue.Set("labels", *fields.Labels)
	}
	if fields.LabelsAdd != nil {
		issue.Set("labels+", *fields.LabelsAdd)
	}
	if fields.LabelsRemove != nil {
		issue.Set("labels-", *fields.LabelsRemove)
	}
}

// updateAssignment commits the complete edit and any matching claim release.
// An empty expectedClaimID means the caller observed no claim, not "any claim".
//
// Clearing the assignee releases the hold, so it follows the release rule
// (LLL-516): only the holder clears it without force, and a forced clear
// leaves the same comment /release does, in the same transaction. Before
// this, 'lll issue update KEY --assignee none' or the board's assignee editor
// released anyone's hold silently, the hole LLL-512 closed on /release.
func updateAssignment(app core.App, issueID, expectedClaimID string, fields assignmentFields, by releaser) (ClaimOutcome, error) {
	var outcome ClaimOutcome
	if fields.Assignee == nil {
		return outcome, &claimRejection{"", "assignment update requires an assignee"}
	}
	err := app.RunInTransaction(func(tx core.App) error {
		issue, err := tx.FindRecordById("issues", issueID)
		if err != nil {
			return err
		}
		held, err := currentClaim(tx, issueID)
		if err != nil {
			return err
		}
		currentID := ""
		if held != nil {
			currentID = held.Id
		}
		if currentID != expectedClaimID {
			return &claimRejection{"claim_changed", "the claim changed; refresh before updating assignment"}
		}
		if held != nil {
			memberID := held.GetString("member")
			name := rosterName(tx, by.memberID, memberID, "someone else")
			if *fields.Assignee != "" && *fields.Assignee != memberID {
				return &claimRejection{"claim_held", fmt.Sprintf("issue is claimed by %s; release the claim before assigning another member", name)}
			}
			if *fields.Assignee == "" {
				name, forced, err := releaseAuthority(tx, held, by)
				if err != nil {
					return err
				}
				if err := tx.Delete(held); err != nil {
					return err
				}
				if forced {
					if err := recordForcedRelease(tx, issue, held, by); err != nil {
						return err
					}
				}
				outcome = ClaimOutcome{ClaimID: held.Id, MemberID: memberID, MemberName: name, ClearedAssignee: true, Forced: forced}
			}
		}
		fields.apply(issue)
		return tx.Save(issue)
	})
	if err != nil {
		return ClaimOutcome{}, err
	}
	return outcome, nil
}

// registerClaimedAssigneeGuard closes the native PATCH side of LLL-516. A
// PATCH that changes a claimed issue's assignee does not release the hold,
// but it takes the issue from its holder all the same, and PATCH carries no
// force and writes no comment. So a PATCH that moves a claimed issue's
// assignee away from the holder is refused unless the holder's own member
// sends it. Anyone else, a superuser included, goes through /assignment or
// /release with force. Assigning the holder is always allowed, as on
// /assignment.
//
// The hook fires after the update rule and scope checks, with the payload
// loaded onto e.Record, so Original() is the stored assignee.
// serializeRecordUpdates holds the issue's lock across the request, the same
// lock the claim routes take, so the claim read here cannot change before
// the save.
func registerClaimedAssigneeGuard(app core.App) {
	app.OnRecordUpdateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		assignee := e.Record.GetString("assignee")
		if assignee == e.Record.Original().GetString("assignee") {
			return e.Next()
		}
		held, err := currentClaim(e.App, e.Record.Id)
		if err != nil {
			return err
		}
		if held == nil || assignee == held.GetString("member") {
			return e.Next()
		}
		if e.Auth != nil && !e.Auth.IsSuperuser() && e.Auth.Id == held.GetString("member") {
			return e.Next()
		}
		viewerID := ""
		if e.Auth != nil && !e.Auth.IsSuperuser() {
			viewerID = e.Auth.Id
		}
		name := rosterName(e.App, viewerID, held.GetString("member"), "an unknown member")
		return withCode(e.BadRequestError(fmt.Sprintf("the claim is held by %s; changing the assignee of another member's claimed issue needs force: clear it through /api/lll/issues/{id}/assignment with force, which releases the claim and comments on the issue",
			byline(name, held.GetString("agent"))), nil), "needs_force")
	})
}
