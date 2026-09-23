package gopb

import (
	"fmt"
	"slices"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/core"
)

// Team-scoped members (members.teams, 1789800000_member_teams.js): the
// collection rules keep a scoped member inside its teams, but the custom
// /api/lll routes read records through the app and skip those rules. Each
// one that takes an issue calls issueInScope first.

// memberSeesTeam reports whether auth may see rows of teamID. Superusers and
// members with no teams see every team.
func memberSeesTeam(auth *core.Record, teamID string) bool {
	if auth == nil {
		return false
	}
	if auth.IsSuperuser() {
		return true
	}
	teams := auth.GetStringSlice("teams")
	return len(teams) == 0 || slices.Contains(teams, teamID)
}

// issueInScope answers 404 for an issue outside the caller's teams, the same
// answer a rule gives, so the route does not reveal that the issue exists.
// An issue that does not exist is left to the route's own handling.
func issueInScope(re *core.RequestEvent, issueID string) error {
	issue, err := re.App.FindRecordById("issues", issueID)
	if err != nil {
		return nil
	}
	if !memberSeesTeam(re.Auth, issue.GetString("team")) {
		return re.NotFoundError("", nil)
	}
	return nil
}

// registerTeamScopeGuard refuses to delete a team that is some member's only
// team. Deleting it would empty that member's teams, and empty means every
// team, so the member would gain access instead of losing it.
func registerTeamScopeGuard(app core.App) {
	app.OnRecordDelete("teams").BindFunc(func(e *core.RecordEvent) error {
		members, err := e.App.FindRecordsByFilter("members", "teams ?= {:id}", "", 0, 0, dbx.Params{"id": e.Record.Id})
		if err != nil {
			return err
		}
		for _, m := range members {
			if len(m.GetStringSlice("teams")) == 1 {
				return fmt.Errorf("team %s is the only team member %s may see; give that member another team or remove them first, because an empty scope means every team",
					e.Record.GetString("key"), m.GetString("name"))
			}
		}
		return e.Next()
	})
}
