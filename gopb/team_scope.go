package gopb

import (
	"slices"

	"github.com/pocketbase/pocketbase/core"
)

// Team-scoped members (members.scope/teams/mode, 1789900000_member_teams.js):
// the collection rules keep a scoped member inside its teams, but the custom
// /api/lll routes read records through the app and skip those rules. Each
// one that takes an issue calls issueWritable first; all of them write.

// memberSeesTeam reports whether auth may see rows of teamID. Superusers and
// scope "all" see every team; scope "teams" sees only the listed ones, so an
// empty list sees nothing.
func memberSeesTeam(auth *core.Record, teamID string) bool {
	if auth == nil {
		return false
	}
	if auth.IsSuperuser() || auth.GetString("scope") == "all" {
		return true
	}
	return slices.Contains(auth.GetStringSlice("teams"), teamID)
}

// issueWritable answers 404 for an issue outside the caller's teams, the same
// answer a rule gives, so the route does not reveal that the issue exists,
// and 403 for a read-only member. An issue that does not exist is left to the
// route's own handling.
func issueWritable(re *core.RequestEvent, issueID string) error {
	issue, err := re.App.FindRecordById("issues", issueID)
	if err != nil {
		return nil
	}
	if !memberSeesTeam(re.Auth, issue.GetString("team")) {
		return re.NotFoundError("", nil)
	}
	if !re.Auth.IsSuperuser() && re.Auth.GetString("mode") != "rw" {
		return re.ForbiddenError("this member is read-only", nil)
	}
	return nil
}

// registerMemberScopeDefault gives a member created without a scope or mode
// its creator's: only a superuser or an "all" + "rw" member passes
// members.createRule, so the default is "all" + "rw". OnRecordCreate rather
// than the Request variant, so seeding and direct saves get it too. Only a
// missing value is filled; "teams" with no teams stays exactly that.
func registerMemberScopeDefault(app core.App) {
	app.OnRecordCreate("members").BindFunc(func(e *core.RecordEvent) error {
		if e.Record.GetString("scope") == "" {
			e.Record.Set("scope", "all")
		}
		if e.Record.GetString("mode") == "" {
			e.Record.Set("mode", "rw")
		}
		return e.Next()
	})
}
