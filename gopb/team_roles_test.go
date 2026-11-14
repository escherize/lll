package gopb

import (
	"github.com/pocketbase/pocketbase/core"
	"testing"
)

func TestMixedRolesSurviveDelegationAndStaleProfileSaves(t *testing.T) {
	f := newCreatorFixture(t)
	teams, err := f.app.FindCollectionByNameOrId("teams")
	if err != nil {
		t.Fatal(err)
	}
	f.members.Fields.Add(&core.RelationField{Name: "editor_teams", CollectionId: teams.Id, MaxSelect: 999})
	if err = f.app.Save(f.members); err != nil {
		t.Fatal(err)
	}
	human := f.reload(t, f.human)
	setAccess(human, access{teams: []string{f.alpha, f.beta}, editors: []string{f.alpha}})
	if err = f.app.Save(human); err != nil {
		t.Fatal(err)
	}
	worker := f.save(t, "bot-mixed-worker", botKind, human.Id, f.coord.Id, nil)
	acc := effectiveAccess(f.app, worker)
	if !acc.writes(f.alpha) || acc.writes(f.beta) || acc.rw {
		t.Fatalf("worker inherited incorrect authority: %#v", acc)
	}
	stale := f.reload(t, human)
	human = f.reload(t, human)
	human.Set("editor_teams", []string{})
	if err = f.app.Save(human); err != nil {
		t.Fatal(err)
	}
	stale.Set("name", "renamed-human")
	if err = f.app.Save(stale); err != nil {
		t.Fatal(err)
	}
	fresh := f.reload(t, human)
	if effectiveAccess(f.app, fresh).hasWrite() || effectiveAccess(f.app, f.reload(t, worker)).hasWrite() {
		t.Fatal("stale save restored a revoked per-team grant")
	}
}

func TestAnEditorGrantDoesNotCreateReadableMembership(t *testing.T) {
	f := newCreatorFixture(t)
	teams, err := f.app.FindCollectionByNameOrId("teams")
	if err != nil {
		t.Fatal(err)
	}
	f.members.Fields.Add(&core.RelationField{Name: "editor_teams", CollectionId: teams.Id, MaxSelect: 999})
	if err = f.app.Save(f.members); err != nil {
		t.Fatal(err)
	}
	_, err = f.create("outside-team", "person", "", "", &access{teams: []string{f.alpha}, editors: []string{f.beta}})
	if err == nil {
		t.Fatal("an Editor-only relation granted hidden team access")
	}
}

func TestBotDefaultsPreserveAllTeamReadWithFiniteEditors(t *testing.T) {
	f := newCreatorFixture(t)
	teams, err := f.app.FindCollectionByNameOrId("teams")
	if err != nil {
		t.Fatal(err)
	}
	f.members.Fields.Add(&core.RelationField{Name: "editor_teams", CollectionId: teams.Id, MaxSelect: 999})
	if err = f.app.Save(f.members); err != nil {
		t.Fatal(err)
	}
	human := f.reload(t, f.human)
	setAccess(human, access{all: true, editors: []string{f.alpha}})
	if err = f.app.Save(human); err != nil {
		t.Fatal(err)
	}
	bot := f.save(t, "bot-default-mixed", botKind, human.Id, "", nil)
	got := effectiveAccess(f.app, bot)
	if !got.all || !got.writes(f.alpha) || got.writes(f.beta) {
		t.Fatalf("mixed wildcard default lost authority: %#v", got)
	}
}
