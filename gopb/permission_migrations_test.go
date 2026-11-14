package gopb

import (
	"os"
	"os/exec"
	"strings"
	"testing"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/plugins/jsvm"
	"github.com/pocketbase/pocketbase/tools/search"
)

// JS migrations register globally in PocketBase. Run this real up/down test
// in its own process so its registry cannot alter sibling fixture tests.
func TestPermissionMigrationsRollbackAndRoundTrip(t *testing.T) {
	const child = "LLL_PERMISSION_MIGRATION_CHILD"
	if os.Getenv(child) != "1" {
		command := exec.Command(os.Args[0], "-test.run=^TestPermissionMigrationsRollbackAndRoundTrip$", "-test.v")
		command.Env = append(os.Environ(), child+"=1")
		if output, err := command.CombinedOutput(); err != nil {
			t.Fatalf("isolated migration rehearsal: %v\n%s", err, output)
		}
		return
	}
	data := t.TempDir()
	dir, err := materializeMigrations(data)
	if err != nil {
		t.Fatal(err)
	}
	app := pocketbase.NewWithConfig(pocketbase.Config{DefaultDataDir: data})
	jsvm.MustRegister(app, jsvm.Config{MigrationsDir: dir, OnInit: bindMigrationsDir(dir)})
	if err := app.Bootstrap(); err != nil {
		t.Fatal(err)
	}
	defer app.ResetBootstrapState()
	if err := app.RunAppMigrations(); err != nil {
		t.Fatal(err)
	}
	collection := func(name string) *core.Collection {
		t.Helper()
		c, err := app.FindCollectionByNameOrId(name)
		if err != nil {
			t.Fatal(err)
		}
		return c
	}
	save := func(record *core.Record) {
		t.Helper()
		if err := app.Save(record); err != nil {
			t.Fatal(err)
		}
	}
	team := core.NewRecord(collection("teams"))
	team.Set("key", "MIG")
	team.Set("name", "Migration")
	save(team)
	member := core.NewRecord(collection("members"))
	member.Set("name", "migration-person")
	member.Set("kind", "person")
	member.Set("workspace_role", "member")
	member.Set("scope", "teams")
	member.Set("teams", []string{team.Id})
	member.Set("mode", "ro")
	member.SetEmail("migration@testing.invalid")
	member.SetRandomPassword()
	save(member)
	full := core.NewRecord(collection("members"))
	full.Set("name", "full-move")
	full.Set("kind", "person")
	full.Set("workspace_role", "member")
	full.Set("scope", "all")
	full.Set("mode", "rw")
	full.SetEmail("move@testing.invalid")
	full.SetRandomPassword()
	save(full)
	destination := core.NewRecord(collection("teams"))
	destination.Set("key", "DEST")
	destination.Set("name", "Destination")
	save(destination)
	issue := core.NewRecord(collection("issues"))
	issue.Set("team", team.Id)
	issue.Set("title", "Native rule move")
	issue.Set("number", 1)
	issue.Set("state", "todo")
	save(issue)
	owned := core.NewRecord(collection("members"))
	owned.Set("name", "bot-unrelated")
	owned.Set("kind", botKind)
	owned.Set("owner", member.Id)
	owned.Set("scope", "all")
	owned.Set("mode", "rw")
	owned.Set("workspace_role", "member")
	owned.SetEmail("owned@testing.invalid")
	owned.SetRandomPassword()
	save(owned)
	info := &core.RequestInfo{Auth: full, Method: "PATCH", Body: map[string]any{"team": destination.Id}}
	allowed, accessErr := app.CanAccessRecord(issue, info, issue.Collection().UpdateRule)
	if !allowed || accessErr != nil {
		resolver := core.NewRecordFieldResolver(app, issue.Collection(), info, true)
		expr, err := search.FilterData(*issue.Collection().UpdateRule).BuildExpr(resolver)
		if err != nil {
			t.Fatal(err)
		}
		query := app.RecordQuery(issue.Collection()).Select("(1)").AndWhere(dbx.HashExp{"issues.id": issue.Id})
		if err := resolver.UpdateQuery(query); err != nil {
			t.Fatal(err)
		}
		t.Fatalf("legacy full member cannot reach native move validation: %v; SQL %s", accessErr, query.AndWhere(expr).Build().SQL())
	}
	// The destination grant must come from this actor and its owner, never
	// an unrelated full writer elsewhere in the virtual members collection.
	member.Set("teams", []string{team.Id, destination.Id})
	member.Set("editor_teams", []string{team.Id})
	save(member)
	for _, actor := range []*core.Record{member, owned} {
		request := &core.RequestInfo{Auth: actor, Method: "PATCH", Body: map[string]any{"team": destination.Id}}
		if allowed, err := app.CanAccessRecord(issue, request, issue.Collection().UpdateRule); err != nil || allowed {
			t.Fatalf("destination Viewer borrowed another writer's grant: allowed=%v err=%v", allowed, err)
		}
	}
	member.Set("editor_teams", []string{team.Id, destination.Id})
	save(member)
	for _, actor := range []*core.Record{member, owned} {
		request := &core.RequestInfo{Auth: actor, Method: "PATCH", Body: map[string]any{"team": destination.Id}}
		if allowed, err := app.CanAccessRecord(issue, request, issue.Collection().UpdateRule); err != nil || !allowed {
			t.Fatalf("mixed/owned Editor move refused: allowed=%v err=%v", allowed, err)
		}
	}
	member.Set("editor_teams", []string{})
	member.Set("teams", []string{team.Id})
	save(member)
	token, err := member.NewAuthToken()
	if err != nil {
		t.Fatal(err)
	}
	key := member.TokenKey()
	runner := core.NewMigrationsRunner(app, core.AppMigrations)
	schemaIntact := func() {
		t.Helper()
		c := collection("members")
		for _, field := range []string{"workspace_role", "editor_teams"} {
			if c.Fields.GetByName(field) == nil {
				t.Fatalf("failed downgrade removed %s", field)
			}
		}
		collection("permission_events")
	}
	blocked := func(message string) {
		t.Helper()
		if _, err := runner.Down(2); err == nil || !strings.Contains(err.Error(), message) {
			t.Fatalf("expected downgrade refusal %q: %v", message, err)
		}
		schemaIntact()
	}
	member.Set("workspace_role", "admin")
	save(member)
	blocked("workspace administrators")
	member.Set("workspace_role", "member")
	save(member)
	event := core.NewRecord(collection("permission_events"))
	event.Set("member", member.Id)
	event.Set("actor_kind", "system")
	event.Set("changes", map[string]any{"scope": "fixture"})
	save(event)
	blocked("Permission history")
	if err := app.Delete(event); err != nil {
		t.Fatal(err)
	}
	member.Set("editor_teams", []string{team.Id})
	save(member)
	// Workspace down runs first; Editor down fails second. PocketBase's native
	// migration runner must roll the entire pair back, including rules/schema.
	blocked("mixed team permissions")
	stored, err := app.FindRecordById("members", member.Id)
	if err != nil {
		t.Fatal(err)
	}
	if !ownAccess(stored).writes(team.Id) || stored.TokenKey() != key {
		t.Fatal("failed downgrade changed grant or credential")
	}
	member.Set("editor_teams", []string{})
	save(member)
	reverted, err := runner.Down(2)
	if err != nil {
		t.Fatal(err)
	}
	if len(reverted) != 2 {
		t.Fatalf("downgrade reverted %v", reverted)
	}
	c := collection("members")
	if c.Fields.GetByName("editor_teams") != nil || c.Fields.GetByName("workspace_role") != nil {
		t.Fatal("safe downgrade retained new fields")
	}
	if _, err := app.FindCollectionByNameOrId("permission_events"); err == nil {
		t.Fatal("safe downgrade retained new audit collection")
	}
	if err := app.RunAppMigrations(); err != nil {
		t.Fatal(err)
	}
	schemaIntact()
	restored, err := app.FindAuthRecordByToken(token, core.TokenTypeAuth)
	if err != nil {
		t.Fatal(err)
	}
	if restored.Id != member.Id || restored.TokenKey() != key || restored.GetString("workspace_role") != "member" || ownAccess(restored).writes(team.Id) || !ownAccess(restored).sees(team.Id) {
		t.Fatal("safe down/up changed identity or legacy access")
	}
}
