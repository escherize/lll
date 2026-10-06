package gopb

import (
	"strings"

	validation "github.com/pocketbase/ozzo-validation/v4"
	"github.com/pocketbase/pocketbase/core"
)

// Board filters split names at commas. Enforce the boundary for every writer,
// including raw API and superuser saves. An unchanged legacy comma name may
// still receive unrelated edits; this rule governs creation and renaming.
func registerFilterNameGuards(app core.App) {
	app.OnRecordValidate("labels", "projects").BindFunc(func(e *core.RecordEvent) error {
		name := e.Record.GetString("name")
		if strings.Contains(name, ",") && (e.Record.IsNew() || name != e.Record.Original().GetString("name")) {
			kind := strings.TrimSuffix(e.Record.Collection().Name, "s")
			return validation.Errors{"name": validation.NewError("validation_filter_name",
				kind+" names cannot contain commas; board filters use commas to separate names. Remove the commas.")}
		}
		return e.Next()
	})
}
