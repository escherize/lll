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
//
// last_editor (LLL-682) is set the same way: on create it is the author,
// whoever named it; on a member's update it is the caller when the update
// changes the doc's content (docContentFields), and the stored editor
// otherwise. Linking an issue, confirming a finding or an empty PATCH is not
// an edit. The docs rules refuse `last_editor` in a member's body, and this
// overwrite is the second lock. A superuser update keeps the stored editor
// unless it names one.
func registerDocAuthor(app core.App) {
	app.OnRecordCreateRequest("docs").BindFunc(func(e *core.RecordRequestEvent) error {
		if isMember(e) {
			e.Record.Set("author", e.Auth.Id)
		}
		e.Record.Set("last_editor", e.Record.GetString("author"))
		return e.Next()
	})
	app.OnRecordUpdateRequest("docs").BindFunc(func(e *core.RecordRequestEvent) error {
		if isMember(e) {
			editor := e.Record.Original().GetString("last_editor")
			if docContentChanged(e.Record) {
				editor = e.Auth.Id
			}
			e.Record.Set("last_editor", editor)
		}
		return e.Next()
	})
}

// The doc fields whose change is an edit: its text and its slug. issues,
// team and the confidence fields are not: linking, moving and confirming
// leave the text as its last editor wrote it.
var docContentFields = []string{"slug", "title", "kind", "body", "area", "paths"}

func docContentChanged(r *core.Record) bool {
	for _, field := range docContentFields {
		if r.GetString(field) != r.Original().GetString(field) {
			return true
		}
	}
	return false
}

func isMember(e *core.RecordRequestEvent) bool {
	return e.Auth != nil && e.Auth.Collection().Name == "members"
}
