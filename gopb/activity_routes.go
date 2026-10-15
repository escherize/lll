package gopb

import (
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
	"net/http"
)

// Older servers ignore unknown webhook fields. An explicit capability check
// prevents a successful-looking registration that only emits issue events.
func registerActivityRoutes(routes *router.Router[*core.RequestEvent]) {
	routes.GET("/api/lll/activity", func(e *core.RequestEvent) error {
		return e.JSON(http.StatusOK, map[string]bool{"supported": true})
	}).Bind(apis.RequireAuth())
}
