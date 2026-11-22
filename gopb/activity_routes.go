package gopb

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

// activityLog is what a client needs to trust a cursor into the audit log
// (LLL-816). Log names this board's log, so a cursor from another board is
// refused instead of read as a position here. Floor and Head are the lowest
// and highest seq the log holds, both 0 while it is empty: a cursor above
// Head was never issued by this log, and one below Floor-1 points past rows
// retention deleted. A team-scoped member cannot read either bound from the
// collection, whose list rule hides other teams' rows.
type activityLog struct {
	Supported bool   `json:"supported"`
	Log       string `json:"log"`
	Floor     int    `json:"floor"`
	Head      int    `json:"head"`
}

// Older servers ignore unknown webhook fields. An explicit capability check
// prevents a successful-looking registration that only emits issue events.
func registerActivityRoutes(routes *router.Router[*core.RequestEvent]) {
	routes.GET("/api/lll/activity", func(e *core.RequestEvent) error {
		out, err := readActivityLog(e.App)
		if err != nil {
			return e.InternalServerError("reading the activity log", err)
		}
		return e.JSON(http.StatusOK, out)
	}).Bind(apis.RequireAuth())
}

func readActivityLog(app core.App) (activityLog, error) {
	out := activityLog{Supported: true}
	events, err := app.FindCachedCollectionByNameOrId("audit_events")
	if err != nil {
		return out, err
	}
	// The collection's creation time is fixed when the board first migrates
	// and travels with a backup, which is the same log.
	sum := sha256.Sum256([]byte(events.Id + "|" + events.Created.String()))
	out.Log = hex.EncodeToString(sum[:6])
	err = app.DB().NewQuery("SELECT COALESCE(MIN(seq), 0), COALESCE(MAX(seq), 0) FROM audit_events").Row(&out.Floor, &out.Head)
	return out, err
}
