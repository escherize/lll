package gopb

import (
	"errors"
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

func TestNativeRecordAuthorityZeroCopiesEscapeAndRollback(t *testing.T) {
	f := newTeamWritesFixture(t)
	record := f.rec(t, "issues", map[string]any{"title": "preserved", "team": f.live.Id})
	var escaped writableRecordRequest
	if err := escaped.commit(); !errors.Is(err, errClosedRecordAuthority) {
		t.Fatalf("zero authority: %v", err)
	}
	stopped := errors.New("abort transaction")
	for _, rollback := range []bool{true, false} {
		event := &core.RecordRequestEvent{RequestEvent: &core.RequestEvent{App: f.app, Auth: f.operator}, Record: record}
		event.Collection = record.Collection()
		err := f.app.OnRecordUpdateRequest().Trigger(event, func(e *core.RecordRequestEvent) error {
			return withWritableRecordRequest(e, func(proof writableRecordRequest) error {
				escaped = proof
				// The native continuation is already bound to this exact event. It
				// cannot be supplied a different record or privileged app by its caller.
				if err := proof.commit(); err != nil {
					return err
				}
				if err := escaped.commit(); !errors.Is(err, errClosedRecordAuthority) {
					t.Fatalf("copied authority reused: %v", err)
				}
				if rollback {
					return stopped
				}
				return nil
			})
		}, func(e *core.RecordRequestEvent) error {
			e.Record.Set("title", "changed")
			return e.App.Save(e.Record)
		})
		if rollback && !errors.Is(err, stopped) {
			t.Fatalf("callback error: %v", err)
		}
		if !rollback && err != nil {
			t.Fatal(err)
		}
		if err := escaped.commit(); !errors.Is(err, errClosedRecordAuthority) {
			t.Fatalf("escaped authority: %v", err)
		}
		stored, err := f.app.FindRecordById("issues", record.Id)
		if err != nil {
			t.Fatal(err)
		}
		want := "changed"
		if rollback {
			want = "preserved"
		}
		if stored.GetString("title") != want {
			t.Fatalf("rollback=%v title=%q", rollback, stored.GetString("title"))
		}
	}
}
