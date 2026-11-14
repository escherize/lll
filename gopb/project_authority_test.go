package gopb

import (
	"errors"
	"net/http/httptest"
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

func TestProjectRemovalProofCannotEscapeReuseOrDeleteAfterRollback(t *testing.T) {
	f := newCascadeFixture(t, 2)
	re := &core.RequestEvent{App: f.app, Auth: f.human, Request: httptest.NewRequest("POST", "/", nil)}
	re.Request.SetPathValue("project", f.project.Id)
	preview, _, err := prepareProjectCascade(f.app, f.human, f.project.Id)
	if err != nil {
		t.Fatal(err)
	}
	var escaped writableProjectCascade
	if _, err := escaped.remove(); !errors.Is(err, errClosedProjectAuthority) {
		t.Fatal(err)
	}
	stopped := errors.New("abort removal")
	_, err = withWritableProjectCascade(re, preview.Revision, func(proof writableProjectCascade) (cascadePreview, error) {
		escaped = proof
		out, err := proof.remove()
		if err != nil {
			return out, err
		}
		if _, err := escaped.remove(); !errors.Is(err, errClosedProjectAuthority) {
			t.Fatal("copied proof reused")
		}
		return out, stopped
	})
	if !errors.Is(err, stopped) {
		t.Fatal(err)
	}
	if _, err := escaped.remove(); !errors.Is(err, errClosedProjectAuthority) {
		t.Fatal("escaped proof reused")
	}
	for _, row := range append(f.issues, f.project) {
		if _, err := f.app.FindRecordById(row.Collection(), row.Id); err != nil {
			t.Fatal("rollback lost a bound record")
		}
	}
	// Viewer can obtain a readable preview but it cannot become write evidence.
	f.human.Set("mode", "ro")
	if err := f.app.Save(f.human); err != nil {
		t.Fatal(err)
	}
	called := false
	if _, err := withWritableProjectCascade(re, preview.Revision, func(proof writableProjectCascade) (cascadePreview, error) { called = true; return proof.remove() }); err == nil || called {
		t.Fatal("read preview became write authority")
	}
}
