package gopb

import (
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/pocketbase/dbx"
	validation "github.com/pocketbase/ozzo-validation/v4"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

// Issue numbers are never reused (LLL-678). An issue key travels: into commit
// messages, branch names, PR bodies and other issues' text. Numbering from the
// highest live issue handed a deleted top issue's number to the next one, so
// an old "ENG-12" silently came to mean a different issue.
//
// issue_counters holds, per team, the highest number the team has issued
// (1792400000_issue_counters.js). Requests cannot write it: every rule is
// null, the fields are hidden, and the request hooks below refuse superusers
// too. The next number is one past the larger of the counter and the highest
// live issue, so a counter behind the data (a team created before counters,
// or one the backfill missed) can only skip numbers, never repeat one.
//
// Who chooses a number:
//   - the server, always, for a member: an explicit number in a member's
//     create is ignored, and a member cannot change an issue's number;
//   - a superuser, explicitly, capped at maxIssueNumber: lll import dir run
//     with a superuser token restores a mirror's own numbers, and the counter
//     moves to the highest of them.
//
// Moving an issue to another team gives it a fresh number there: it never
// carries its old number into the new team.
const issueCounters = "issue_counters"

// maxIssueNumber is the ceiling on issues.number and issue_counters.last,
// far below 2^53 so a number survives JSON and float64 untouched.
const maxIssueNumber = 999_999_999

const repairHint = "a superuser renumbers or deletes that issue, then lowers the counter with POST /api/lll/teams/{team}/issue-counter"

// findCounter is the team's counter, or a new unsaved one.
func findCounter(app core.App, team string) (*core.Record, error) {
	counter, err := app.FindFirstRecordByFilter(issueCounters, "team = {:team}", dbx.Params{"team": team})
	if errors.Is(err, sql.ErrNoRows) {
		collection, ferr := app.FindCachedCollectionByNameOrId(issueCounters)
		if ferr != nil {
			return nil, fmt.Errorf("issue counters: %w", ferr)
		}
		counter = core.NewRecord(collection)
		counter.Set("team", team)
		return counter, nil
	}
	return counter, err
}

// nextIssueNumber settles `record`'s number in its team and moves the team's
// counter to it, inside the caller's transaction (`app` is the transaction),
// so the save and the counter commit together or not at all.
//
// A number already on the record was let through by the request hooks (a
// superuser's) or set by the server's own code; it is kept,
// and the unique (team, number) index still refuses a live duplicate. 0 asks
// for the next number.
func nextIssueNumber(app core.App, record *core.Record) error {
	team := record.GetString("team")
	counter, err := findCounter(app, team)
	if err != nil {
		return err
	}
	number := record.GetInt("number")
	if number == 0 {
		highest, holder, err := highestIssue(app, team, record.Id)
		if err != nil {
			return err
		}
		number = max(counter.GetInt("last"), highest) + 1
		if number > maxIssueNumber {
			return exhausted(app, team, holder)
		}
		record.Set("number", number)
	} else if number < 0 || number > maxIssueNumber {
		return validation.Errors{"number": validation.NewError("validation_number_ceiling",
			fmt.Sprintf("an issue number runs from 1 to %d", maxIssueNumber))}
	}
	changed := false
	if number > counter.GetInt("last") {
		counter.Set("last", number)
		changed = true
	}
	if changed {
		return app.Save(counter)
	}
	return nil
}

// highestIssue is the team's highest live number and the issue holding it,
// leaving out `except` (the issue being moved in).
func highestIssue(app core.App, team, except string) (int, *core.Record, error) {
	last, err := app.FindRecordsByFilter("issues", "team = {:team} && id != {:except}", "-number", 1, 0,
		dbx.Params{"team": team, "except": except})
	if err != nil {
		return 0, nil, err
	}
	if len(last) == 0 {
		return 0, nil, nil
	}
	return last[0].GetInt("number"), last[0], nil
}

// exhausted names the issue holding the team's top number and the repair.
func exhausted(app core.App, team string, holder *core.Record) error {
	key := team
	if t, err := app.FindRecordById("teams", team); err == nil {
		key = t.GetString("key")
	}
	held := "its counter"
	if holder != nil {
		held = fmt.Sprintf("%s-%d", key, holder.GetInt("number"))
	}
	return validation.Errors{"number": validation.NewError("validation_numbers_exhausted",
		fmt.Sprintf("team %s has used every issue number up to %d (%s holds the highest); %s", key, maxIssueNumber, held, repairHint))}
}

// registerIssueNumbering binds the request rules above and the team-move
// renumbering, and keeps issue_counters the server's.
func registerIssueNumbering(app core.App) {
	app.OnRecordCreateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		number := e.Record.GetInt("number")
		if number != 0 && !e.HasSuperuserAuth() {
			e.Record.Set("number", 0)
		}
		return e.Next()
	})
	app.OnRecordUpdateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		if !e.HasSuperuserAuth() && e.Record.GetInt("number") != e.Record.Original().GetInt("number") {
			return e.BadRequestError("an issue's number is the server's: it is assigned at create and on a move to another team", nil)
		}
		return e.Next()
	})
	app.OnRecordUpdate("issues").BindFunc(func(e *core.RecordEvent) error {
		moved := e.Record.GetString("team") != e.Record.Original().GetString("team")
		renumbered := e.Record.GetInt("number") != e.Record.Original().GetInt("number")
		if !moved && !renumbered {
			return e.Next()
		}
		originalApp := e.App
		defer func() { e.App = originalApp }()
		return originalApp.RunInTransaction(func(txApp core.App) error {
			e.App = txApp
			if moved && !renumbered {
				e.Record.Set("number", 0)
			}
			if err := nextIssueNumber(txApp, e.Record); err != nil {
				return err
			}
			return e.Next()
		})
	})

	serverOnly := func(e *core.RecordRequestEvent) error {
		return e.ForbiddenError("issue counters are kept by the server; a superuser repairs one through POST /api/lll/teams/{team}/issue-counter", nil)
	}
	app.OnRecordCreateRequest(issueCounters).BindFunc(serverOnly)
	app.OnRecordUpdateRequest(issueCounters).BindFunc(serverOnly)
	app.OnRecordDeleteRequest(issueCounters).BindFunc(serverOnly)
}

// repairIssueCounter sets a team's counter to `last`, which may not go below
// the team's highest live issue. It returns the value it replaced.
func repairIssueCounter(app core.App, teamID string, last int) (int, error) {
	if last < 0 || last > maxIssueNumber {
		return 0, fmt.Errorf("last must be between 0 and %d", maxIssueNumber)
	}
	var previous int
	err := app.RunInTransaction(func(tx core.App) error {
		if _, err := tx.FindRecordById("teams", teamID); err != nil {
			return err
		}
		highest, _, err := highestIssue(tx, teamID, "")
		if err != nil {
			return err
		}
		if last < highest {
			return fmt.Errorf("the team's highest issue is number %d; renumber or delete it first, the counter cannot go below it", highest)
		}
		counter, err := findCounter(tx, teamID)
		if err != nil {
			return err
		}
		previous = counter.GetInt("last")
		counter.Set("last", last)
		return tx.Save(counter)
	})
	return previous, err
}

// registerIssueCounterRoutes: the counter repair, superuser only, a reason
// required, and every change logged with who made it and what it replaced.
func registerIssueCounterRoutes(routes *router.Router[*core.RequestEvent]) {
	// The records API's truncate deletes every counter at once, outside the
	// record request hooks: refused like any other counter write.
	routes.BindFunc(func(re *core.RequestEvent) error {
		if re.Request.Method == http.MethodDelete && strings.HasSuffix(re.Request.URL.Path, "/truncate") {
			name := strings.TrimSuffix(strings.TrimPrefix(re.Request.URL.Path, "/api/collections/"), "/truncate")
			if c, err := re.App.FindCachedCollectionByNameOrId(name); err == nil && c.Name == issueCounters {
				return re.ForbiddenError("issue counters are kept by the server; a superuser repairs one through POST /api/lll/teams/{team}/issue-counter", nil)
			}
		}
		return re.Next()
	})
	routes.POST("/api/lll/teams/{team}/issue-counter", func(re *core.RequestEvent) error {
		var body struct {
			Last   *int   `json:"last"`
			Reason string `json:"reason"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 2048)
		if err := re.BindBody(&body); err != nil || body.Last == nil {
			return re.BadRequestError("a counter repair names the new 'last' and a 'reason'", nil)
		}
		reason := strings.TrimSpace(body.Reason)
		if reason == "" {
			return re.BadRequestError("a counter repair needs a reason; it is logged", nil)
		}
		team := re.Request.PathValue("team")
		previous, err := repairIssueCounter(re.App, team, *body.Last)
		if errors.Is(err, sql.ErrNoRows) {
			return re.NotFoundError("no such team", nil)
		}
		if err != nil {
			return re.BadRequestError(err.Error(), nil)
		}
		re.App.Logger().Warn("issue counter repaired",
			"team", team, "from", previous, "to", *body.Last, "by", re.Auth.Id+" "+re.Auth.Email(), "reason", reason)
		return re.JSON(http.StatusOK, map[string]any{"team": team, "from": previous, "to": *body.Last})
	}).Bind(apis.RequireSuperuserAuth())
}
