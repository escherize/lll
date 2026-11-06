package gopb

import (
	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/core"
)

// The record may have been loaded before another write updated its activity.
// Read the current date in the same writer transaction, never from the caller's
// record. This also discards forged dates on no-op saves and raw model writes.
func preserveIssueActivity(tx core.App, r *core.Record, action string) error {
	if r.Collection().Name != "issues" || r.Collection().Fields.GetByName("last_activity") == nil {
		return nil
	}
	date := ""
	if action != "create" {
		current, err := tx.FindRecordById("issues", r.Id)
		if err != nil {
			return err
		}
		date = current.GetString("last_activity")
	}
	r.Set("last_activity", date)
	return nil
}

// An activity date is a materialized read field, not another issue edit. Use
// the existing audit timestamp and transaction without Save(issue): that would
// change updated, trigger an issue event and recursively audit its own write.
// A missing field is possible while earlier embedded migrations are running.
func advanceIssueActivity(tx core.App, r *core.Record, issueID, at string) error {
	issues, err := tx.FindCachedCollectionByNameOrId("issues")
	if err != nil {
		return err
	}
	if issues.Fields.GetByName("last_activity") == nil || issueID == "" {
		return nil
	}
	_, err = tx.DB().NewQuery("UPDATE issues SET last_activity = MAX(COALESCE(last_activity, ''), {:at}) WHERE id = {:id}").
		Bind(dbx.Params{"at": at, "id": issueID}).Execute()
	if err != nil {
		return err
	}
	if r.Collection().Name == "issues" {
		if current, err := tx.FindRecordById("issues", issueID); err == nil {
			r.Set("last_activity", current.GetString("last_activity"))
		}
	}
	return nil
}
