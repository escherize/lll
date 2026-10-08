package gopb

import (
	"fmt"

	validation "github.com/pocketbase/ozzo-validation/v4"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

// LLL-660: an archived team is read-only, for every writer.
//
// Archiving used to be checked only where lll's own code remembered to (the
// CLI's create, the board's actions, /refs). A raw PATCH, a new comment, the
// /claim and /assignment routes and a superuser all wrote to an archived
// team. The rule now lives here, on the server:
//
//   - the records API: OnRecord{Create,Update,Delete}Request on every
//     collection that holds a team's records (archivedGuarded). An update is
//     checked against the record's stored team and its new one, so a record
//     can neither leave nor enter an archived team.
//   - the custom /api/lll routes: issueWritable calls archivedRefusal, so
//     claim, renew, release, assignment and refs refuse the same way.
//
// Request hooks rather than model hooks, on purpose: PocketBase's own
// bookkeeping saves through the model layer too. Deleting a member clears
// its id from every issue it was assigned (SaveNoValidate on each), and the
// claim sweep releases a dead hold; a model hook would make both fail on an
// archived team. Neither is a person writing to the team.
//
// The teams collection is not guarded: unarchiving is a team update.

// archivedGuarded is every collection whose records belong to one team:
// directly (team) or through their issue (issue).
var archivedGuarded = []string{"issues", "comments", "claims", "docs", "labels", "projects"}

// recordTeam is the id of the team record belongs to, "" when it has none
// or its issue no longer exists.
func recordTeam(app core.App, record *core.Record) string {
	switch record.Collection().Name {
	case "comments", "claims":
		issue, err := app.FindRecordById("issues", record.GetString("issue"))
		if err != nil {
			return ""
		}
		return issue.GetString("team")
	default:
		return record.GetString("team")
	}
}

// archivedRefusal is the one answer to a write into an archived team: 403,
// naming the team and the way back. A team auth cannot see is left to the
// collection rules, so the refusal never confirms that a hidden team exists.
func archivedRefusal(app core.App, auth *core.Record, teamID string) error {
	if teamID == "" {
		return nil
	}
	team, err := app.FindRecordById("teams", teamID)
	if err != nil || !team.GetBool("archived") {
		return nil
	}
	if auth != nil && !effectiveAccess(app, auth).sees(teamID) {
		return nil
	}
	key := team.GetString("key")
	return router.NewForbiddenError(fmt.Sprintf(
		"team %s is archived, so its records are read-only; 'lll team unarchive %s' brings it back", key, key), nil)
}

func registerArchivedTeamGuard(app core.App) {
	check := func(e *core.RecordRequestEvent) error {
		teams := []string{recordTeam(e.App, e.Record)}
		if !e.Record.IsNew() {
			teams = append(teams, recordTeam(e.App, e.Record.Original()))
		}
		for _, team := range teams {
			if err := archivedRefusal(e.App, e.Auth, team); err != nil {
				return err
			}
		}
		return e.Next()
	}
	app.OnRecordCreateRequest(archivedGuarded...).BindFunc(check)
	app.OnRecordUpdateRequest(archivedGuarded...).BindFunc(check)
	app.OnRecordDeleteRequest(archivedGuarded...).BindFunc(check)
}

// LLL-670: an issue's assignee can see the issue's team.
//
// Assigning a member who cannot read the team gave them work they could not
// open, and showed the team's members "a hidden member". Checked when the
// assignee or the team changes, on every save (records API, /claim,
// /assignment, the app's own saves), so a narrowed member keeps the issues
// already assigned to them but cannot be handed new ones. Clearing the
// assignee is always allowed, which is how deleting a member clears it.
func checkAssigneeSeesTeam(app core.App, record *core.Record) error {
	assignee := record.GetString("assignee")
	team := record.GetString("team")
	if assignee == "" {
		return nil
	}
	if !record.IsNew() {
		before := record.Original()
		if before.GetString("assignee") == assignee && before.GetString("team") == team {
			return nil
		}
	}
	member, err := app.FindRecordById("members", assignee)
	if err != nil {
		return nil // the relation validator reports a missing member
	}
	if effectiveAccess(app, member).sees(team) {
		return nil
	}
	// The member is not named: a team-scoped caller may not see them.
	key := teamKey(app, team)
	return validation.Errors{"assignee": validation.NewError("validation_assignee_team", fmt.Sprintf(
		"the assignee cannot see team %s, so they cannot be assigned its issues. Assign a member with access to %s, or widen theirs: lll member access NAME --add-team %s",
		key, key, key))}
}

func registerAssigneeTeamGuard(app core.App) {
	check := func(e *core.RecordEvent) error {
		if err := checkAssigneeSeesTeam(e.App, e.Record); err != nil {
			return err
		}
		return e.Next()
	}
	app.OnRecordCreate("issues").BindFunc(check)
	app.OnRecordUpdate("issues").BindFunc(check)
}
