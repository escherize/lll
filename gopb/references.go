package gopb

import (
	"net/http"
	"strings"
	"unicode"
	"unicode/utf8"

	validation "github.com/pocketbase/ozzo-validation/v4"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

type referenceOutcome struct {
	Refs  string `json:"refs"`
	Added bool   `json:"added"`
}

func mergeReference(existing, reference string) (referenceOutcome, error) {
	if reference == "" || strings.IndexFunc(reference, func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) }) >= 0 {
		return referenceOutcome{}, validation.Errors{"ref": validation.NewError("validation_reference", "A reference must be one nonempty token without whitespace or control characters.")}
	}
	for _, value := range strings.Fields(existing) {
		if value == reference {
			return referenceOutcome{Refs: existing}, nil
		}
	}
	separator := ""
	last, _ := utf8.DecodeLastRuneInString(existing)
	if existing != "" && !unicode.IsSpace(last) {
		separator = " "
	}
	return referenceOutcome{Refs: existing + separator + reference, Added: true}, nil
}

func appendReference(app core.App, issueID, reference string) (referenceOutcome, error) {
	var result referenceOutcome
	err := app.RunInTransaction(func(tx core.App) error {
		issue, err := tx.FindRecordById("issues", issueID)
		if err != nil {
			return err
		}
		team, err := tx.FindRecordById("teams", issue.GetString("team"))
		if err != nil {
			return err
		}
		if team.GetBool("archived") {
			return validation.Errors{"ref": validation.NewError("validation_archived", "Team is archived; unarchive it before adding references.")}
		}
		result, err = mergeReference(issue.GetString("refs"), reference)
		if err != nil || !result.Added {
			return err
		}
		issue.Set("refs", result.Refs)
		return tx.Save(issue)
	})
	return result, err
}

func registerReferenceRoutes(routes *router.Router[*core.RequestEvent], writes *issueWriteLocks) {
	routes.POST("/api/lll/issues/{issue}/refs", func(re *core.RequestEvent) error {
		var body struct {
			Ref string `json:"ref"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 8192)
		if err := re.BindBody(&body); err != nil {
			return re.BadRequestError("invalid reference request", nil)
		}
		unlock := writes.acquire(re.Request.PathValue("issue"))
		defer unlock()
		result, err := appendReference(re.App, re.Request.PathValue("issue"), body.Ref)
		if err == nil {
			return re.JSON(http.StatusOK, result)
		}
		return writeFailure(re, err, "issue or team no longer exists", "invalid reference", "reference transaction failed")
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
}
