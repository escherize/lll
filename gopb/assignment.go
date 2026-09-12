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
}

// updateAssignment commits the complete edit and any matching claim release.
// An empty expectedClaimID means the caller observed no claim, not "any claim".
func updateAssignment(app core.App, issueID, expectedClaimID string, fields assignmentFields) (ClaimOutcome, error) {
	var outcome ClaimOutcome
	if fields.Assignee == nil {
		return outcome, &claimRejection{"assignment update requires an assignee"}
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
			return &claimRejection{"the claim changed; refresh before updating assignment"}
		}
		if held != nil {
			memberID := held.GetString("member")
			name := "someone else"
			if member, err := tx.FindRecordById("members", memberID); err == nil {
				name = member.GetString("name")
			}
			if *fields.Assignee != "" && *fields.Assignee != memberID {
				return &claimRejection{fmt.Sprintf("issue is claimed by %s; release the claim before assigning another member", name)}
			}
			if *fields.Assignee == "" {
				if err := tx.Delete(held); err != nil {
					return err
				}
				outcome = ClaimOutcome{ClaimID: held.Id, MemberID: memberID, MemberName: name, ClearedAssignee: true}
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
