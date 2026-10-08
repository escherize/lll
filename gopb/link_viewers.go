package gopb

import (
	"net/http"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

// Team links (LLL-658). A "KEY.MAC" board link opens one team, read-only, and
// names no member. The board reads every page with its viewer's own
// credential, so the collection rules alone decide what a viewer sees; a link
// has no credential, so the server keeps one per team in the link_viewers
// collection (1792465800_link_viewers.js): scope "teams", that one team, mode
// "ro". The rules read it exactly as they read a read-only guest of the team.

const linkViewers = "link_viewers"

// registerLinkTokenRoute answers POST /api/lll/link-token {"team": KEY} with
// a token for team KEY's link viewer, creating the viewer on first use.
//
// Only a caller whose effective access is every team may ask: the board's
// own member. Such a caller already reads everything a link viewer can, so
// the token never widens anyone; a scoped caller is refused, because a token
// for a team outside its scope would be. The board keeps the token on the
// server and the browser never sees it. An unknown key answers 404.
func registerLinkTokenRoute(routes *router.Router[*core.RequestEvent]) {
	routes.POST("/api/lll/link-token", func(re *core.RequestEvent) error {
		if re.Auth == nil || !effectiveAccess(re.App, re.Auth).all {
			return re.ForbiddenError("only a login with access to every team may open a team link", nil)
		}
		var body struct {
			Team string `json:"team"`
		}
		if err := re.BindBody(&body); err != nil || body.Team == "" {
			return re.BadRequestError("name the team: {\"team\": KEY}", err)
		}
		team, err := re.App.FindFirstRecordByData("teams", "key", body.Team)
		if err != nil {
			return re.NotFoundError("", nil)
		}
		viewer, err := linkViewer(re.App, team.Id)
		if err != nil {
			return re.InternalServerError("failed to prepare the team link's reader", err)
		}
		token, err := viewer.NewAuthToken()
		if err != nil {
			return re.InternalServerError("failed to mint the team link's token", err)
		}
		return re.JSON(http.StatusOK, map[string]string{"token": token})
	})
}

// linkViewer is team teamID's link viewer, created when it does not exist.
// Its id is the team's id, so two concurrent first uses cannot create two:
// the loser's save fails on the primary key and it reads the winner's.
func linkViewer(app core.App, teamID string) (*core.Record, error) {
	if found, err := app.FindRecordById(linkViewers, teamID); err == nil {
		return found, nil
	}
	collection, err := app.FindCollectionByNameOrId(linkViewers)
	if err != nil {
		return nil, err
	}
	viewer := core.NewRecord(collection)
	viewer.Id = teamID
	viewer.Set("teams", []string{teamID})
	viewer.Set("scope", "teams")
	viewer.Set("mode", "ro")
	viewer.SetEmail(teamID + "@links.invalid")
	viewer.SetRandomPassword()
	if err := app.Save(viewer); err != nil {
		if found, findErr := app.FindRecordById(linkViewers, teamID); findErr == nil {
			return found, nil
		}
		return nil, err
	}
	return viewer, nil
}
