package gopb

import (
	"os"
	"os/exec"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/plugins/jsvm"
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
