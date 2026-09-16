package gopb

import (
	"net/http"
	"strings"
	"time"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
	"github.com/pocketbase/pocketbase/tools/types"
)

// registerIssuePrecondition binds the If-Unmodified-Since optimistic-write
// check to issues updates (LLL-399). LLL-391's --if-unchanged-since checked
// the stamp on the client between its read and its PATCH, so a write landing
// inside that round trip was clobbered anyway. The precondition has to hold
// at the write, which only the server can see: a PATCH carrying the header
// is refused with 412 unless the stamp names the record's current 'updated'.
//
// OnRecordUpdateRequest (not OnRecordUpdate) because only the request
// variant carries the HTTP header, and the precondition is meaningless for
// internal saves: the hook fires after the record is loaded from the
// database and before form.Submit() applies the payload, so e.Record's
// 'updated' is exactly the value the caller read. Patches without the
// header — the board's own moves, the web editors, every other client —
// behave exactly as before.
func registerIssuePrecondition(app core.App) {
	app.OnRecordUpdateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		stamp := strings.TrimSpace(e.Request.Header.Get("If-Unmodified-Since"))
		if stamp == "" {
			return e.Next()
		}
		if err := checkUnmodified(e.Record, stamp); err != nil {
			return err
		}
		return e.Next()
	})
}

// checkUnmodified refuses with 412 when `stamp` does not name the record's
// current 'updated', and with 400 when it is not a PocketBase stamp at all.
// types.ParseDateTime is no use for validation — its string scan falls back
// to spf13/cast and answers zero-time, nil for garbage — so the stamp is
// parsed with time.Parse at the wire layout. Both sides are compared at
// millisecond precision: the wire value carries exactly that, and a stamp
// the client echoed from a read must never fail for digits the JSON never
// showed.
func checkUnmodified(record *core.Record, stamp string) error {
	parsed, err := time.Parse(types.DefaultDateLayout, stamp)
	if err != nil {
		return router.NewApiError(http.StatusBadRequest,
			"If-Unmodified-Since must be the 'updated' stamp a read returned, "+
				"formatted as "+types.DefaultDateLayout+" - got '"+stamp+"'", nil)
	}
	current := record.GetDateTime("updated")
	ms := func(t time.Time) time.Time { return t.UTC().Truncate(time.Millisecond) }
	if ms(parsed).Equal(ms(current.Time())) {
		return nil
	}
	return router.NewApiError(http.StatusPreconditionFailed,
		"the record changed since "+stamp+": its 'updated' is now "+current.String()+
			" — read it again and retry with that stamp", nil)
}
