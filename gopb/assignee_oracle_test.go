package gopb

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
)

func TestAssigneeMissingAndHiddenHaveTheSameHTTPRefusal(t *testing.T) {
	for _, method := range []string{http.MethodPost, http.MethodPatch} {
		t.Run(method, func(t *testing.T) {
			f := newCreatorFixture(t)
			hidden := f.save(t, "hidden-person", "person", "", "", &access{teams: []string{f.beta}, rw: true})
			issues := core.NewBaseCollection("issues")
			issues.Fields.Add(&core.TextField{Name: "title"}, &core.TextField{Name: "team"}, &core.RelationField{Name: "assignee", CollectionId: f.members.Id, MaxSelect: 1})
			rule := `@request.auth.id != ""`
			issues.CreateRule, issues.UpdateRule, issues.ViewRule = &rule, &rule, &rule
			if err := f.app.Save(issues); err != nil {
				t.Fatal(err)
			}
			registerAssigneeTeamGuard(f.app)
			issue := core.NewRecord(issues)
			issue.Set("title", "before")
			issue.Set("team", f.alpha)
			if err := f.app.Save(issue); err != nil {
				t.Fatal(err)
			}
			token, err := f.coord.NewAuthToken()
			if err != nil {
				t.Fatal(err)
			}
			routes, err := apis.NewRouter(f.app)
			if err != nil {
				t.Fatal(err)
			}
			mux, err := routes.BuildMux()
			if err != nil {
				t.Fatal(err)
			}
			request := func(verb, id, assignee string) (int, string) {
				path := "/api/collections/issues/records"
				if verb == http.MethodPatch {
					path += "/" + id
				}
				body := fmt.Sprintf(`{"team":%q,"title":"probe","assignee":%q}`, f.alpha, assignee)
				req := httptest.NewRequest(verb, path, strings.NewReader(body))
				req.Header.Set("Content-Type", "application/json")
				req.Header.Set("Authorization", "Bearer "+token)
				out := httptest.NewRecorder()
				mux.ServeHTTP(out, req)
				return out.Code, out.Body.String()
			}
			hiddenCode, hiddenBody := request(method, issue.Id, hidden.Id)
			missingCode, missingBody := request(method, issue.Id, "xxxxxxxxxxxxxxx")
			if hiddenCode != 400 || missingCode != 400 {
				t.Fatalf("hidden=%d missing=%d", hiddenCode, missingCode)
			}
			if hiddenBody != missingBody {
				t.Errorf("member existence changes the wire error:\nhidden: %s\nmissing: %s", hiddenBody, missingBody)
			}
			if strings.Contains(hiddenBody, hidden.Id) || strings.Contains(hiddenBody, hidden.GetString("name")) {
				t.Error("refusal exposes the hidden member")
			}
			validCode, validBody := request(method, issue.Id, f.coord.Id)
			if validCode != 200 {
				t.Fatalf("valid assignment refused: %d %s", validCode, validBody)
			}
			var assigned struct {
				ID       string `json:"id"`
				Assignee string `json:"assignee"`
			}
			if err = json.Unmarshal([]byte(validBody), &assigned); err != nil {
				t.Fatal(err)
			}
			stored, err := f.app.FindRecordById("issues", assigned.ID)
			if err != nil || stored.GetString("assignee") != f.coord.Id {
				t.Fatalf("valid assignment not persisted: %v", err)
			}
			clearCode, clearBody := request(http.MethodPatch, assigned.ID, "")
			if clearCode != 200 {
				t.Fatalf("clearing refused: %d %s", clearCode, clearBody)
			}
			stored, err = f.app.FindRecordById("issues", assigned.ID)
			if err != nil || stored.GetString("assignee") != "" {
				t.Fatalf("clearing was not persisted: %v", err)
			}
		})
	}
}
