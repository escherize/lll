package gopb

import (
	validation "github.com/pocketbase/ozzo-validation/v4"
	"github.com/pocketbase/pocketbase/core"
)

// Member API requests attribute creation to the authenticated account. A
// superuser-backed board can explicitly attribute its configured actor.
func registerIssueProvenance(app core.App) {
	app.OnRecordValidate("issues").BindFunc(func(e *core.RecordEvent) error {
		// JSON storage must remain readable by the typed issue consumers.
		// null is the historical/unknown value; supplied coordinates are text.
		var origin map[string]string
		if err := e.Record.UnmarshalJSONField("origin", &origin); err != nil {
			return validation.Errors{"origin": validation.NewError("validation_invalid_origin", "Origin must be an object with text values, or null.")}
		}
		return e.Next()
	})
	app.OnRecordCreateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		if e.Auth != nil && e.Auth.Collection().Name == "members" {
			e.Record.Set("creator", e.Auth.Id)
		}
		return e.Next()
	})
}

// A doc's author is the member whose token created it (LLL-618). The docs
// rules refuse `author` in a member's body, so this is the only way a member
// write sets it; a superuser has no member identity and stays authorless
// unless it names one.
func registerDocAuthor(app core.App) {
	app.OnRecordCreateRequest("docs").BindFunc(func(e *core.RecordRequestEvent) error {
		if e.Auth != nil && e.Auth.Collection().Name == "members" {
			e.Record.Set("author", e.Auth.Id)
		}
		return e.Next()
	})
}
