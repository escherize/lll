package gopb

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"mime"
	"net/http"
	"strings"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

// Older PocketBase servers ignore unknown headers. A flagged CLI create
// checks this authenticated endpoint before writing rather than assuming
// that sending Idempotency-Key established a guarantee.
func registerIssueIdempotencyRoutes(routes *router.Router[*core.RequestEvent]) {
	routes.GET("/api/lll/issues/idempotency", func(e *core.RequestEvent) error {
		return e.JSON(http.StatusOK, map[string]bool{"supported": true})
	}).Bind(apis.RequireAuth())
}

func registerIssueIdempotency(app core.App) {
	// Metadata is server-owned, including when an API client supplies fields
	// directly. Updates preserve the original creation fingerprint.
	app.OnRecordUpdateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		for _, name := range []string{"idempotency_key", "idempotency_fingerprint"} {
			e.Record.Set(name, e.Record.Original().GetString(name))
		}
		return e.Next()
	})
	app.OnRecordCreateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		e.Record.Set("idempotency_key", "")
		e.Record.Set("idempotency_fingerprint", "")
		key := strings.TrimSpace(e.Request.Header.Get("Idempotency-Key"))
		if key == "" {
			if _, present := e.Request.Header["Idempotency-Key"]; present {
				return e.BadRequestError("Idempotency-Key must not be empty", nil)
			}
			return e.Next()
		}
		media, _, err := mime.ParseMediaType(e.Request.Header.Get("Content-Type"))
		if err != nil || media != "application/json" {
			return e.BadRequestError("Idempotency-Key requires an application/json creation request", nil)
		}
		info, err := e.RequestInfo()
		if err != nil {
			return err
		}
		payload := make(map[string]any, len(info.Body))
		for name, value := range info.Body {
			if name != "idempotency_key" && name != "idempotency_fingerprint" {
				payload[name] = value
			}
		}
		if e.Auth != nil && e.Auth.Collection().Name == "members" {
			payload["creator"] = e.Auth.Id
		}
		canonical, err := json.Marshal(payload)
		if err != nil {
			return e.BadRequestError("cannot fingerprint the creation payload", err)
		}
		digest := sha256.Sum256(canonical)
		fingerprint := hex.EncodeToString(digest[:])

		originalApp := e.App
		defer func() { e.App = originalApp }()
		var reused *core.Record
		err = originalApp.RunInTransaction(func(tx core.App) error {
			e.App = tx
			existing, err := tx.FindFirstRecordByFilter("issues",
				"team={:team} && idempotency_key={:key}",
				dbx.Params{"team": e.Record.GetString("team"), "key": key})
			if err == nil {
				if existing.GetString("idempotency_fingerprint") != fingerprint {
					return router.NewApiError(http.StatusConflict,
						"Idempotency-Key '"+key+"' was already used for a different creation payload", nil)
				}
				reused = existing
				return nil
			}
			if !errors.Is(err, sql.ErrNoRows) {
				return err
			}
			e.Record.Set("idempotency_key", key)
			e.Record.Set("idempotency_fingerprint", fingerprint)
			return e.Next()
		})
		e.App = originalApp
		if err != nil || reused == nil {
			return err
		}
		e.Record = reused
		if err := apis.EnrichRecord(e.RequestEvent, reused); err != nil {
			return err
		}
		result := reused.PublicExport()
		result["reused"] = true
		return e.JSON(http.StatusOK, result)
	})
}
