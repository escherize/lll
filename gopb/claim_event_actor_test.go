package gopb

import (
	"github.com/pocketbase/pocketbase/core"
	"testing"
	"time"
)

func TestClaimEventsKeepReleaserSeparateAndIdentifyExpiry(t *testing.T) {
	app, issue, holder, rescuer := claimFixture(t)
	collection, err := app.FindCollectionByNameOrId("claims")
	if err != nil {
		t.Fatal(err)
	}
	members, _ := app.FindCollectionByNameOrId("members")
	collection.Fields.Add(&core.RelationField{Name: "event_actor", CollectionId: members.Id, MaxSelect: 1},
		&core.TextField{Name: "event_agent"}, &core.TextField{Name: "event_source"})
	if err := app.Save(collection); err != nil {
		t.Fatal(err)
	}
	type seen struct{ actor, agent, source, holder string }
	var deleted []seen
	app.OnRecordAfterDeleteSuccess("claims").BindFunc(func(e *core.RecordEvent) error {
		fresh := e.Record.Fresh() // the same schema-only copy realtime sends
		deleted = append(deleted, seen{fresh.GetString("event_actor"), fresh.GetString("event_agent"), fresh.GetString("event_source"), fresh.GetString("member")})
		return e.Next()
	})
	held, err := acquireClaim(app, issue, holder, "worker")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := renewClaim(app, issue, held.ClaimID, holder, "worker"); err != nil {
		t.Fatal(err)
	}
	stored, _ := app.FindRecordById("claims", held.ClaimID)
	if stored.GetString("event_actor") != holder {
		t.Fatal("renewal lost actor")
	}
	if _, err := releaseClaim(app, issue, held.ClaimID, releaser{memberID: rescuer, agent: "recovery", force: true}); err != nil {
		t.Fatal(err)
	}
	if len(deleted) != 1 || deleted[0] != (seen{rescuer, "recovery", "member", holder}) {
		t.Fatalf("wrong forced-release actor: %+v", deleted)
	}
	if _, err := acquireClaim(app, issue, holder, "worker"); err != nil {
		t.Fatal(err)
	}
	n, err := expireClaims(app, time.Now().Add(claimMaxAge+time.Minute), claimMaxAge)
	if err != nil || n != 1 {
		t.Fatalf("expiry: %d %v", n, err)
	}
	if len(deleted) != 2 || deleted[1] != (seen{"", "", "system", holder}) {
		t.Fatalf("expiry impersonated a holder: %+v", deleted)
	}
}
