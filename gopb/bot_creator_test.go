package gopb

import (
	"errors"
	"slices"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
	"github.com/pocketbase/pocketbase/tools/router"
)

// LLL-709: a bot creates a bot for its own human owner. The new bot is owned
// by that person (one hop, as before), records the bot that created it in
// created_by, and is never wider than its creator, then or later.
type creatorFixture struct {
	app          core.App
	members      *core.Collection
	alpha, beta  string
	human, other *core.Record // people with every team, read-write
	coord        *core.Record // a bot of human's: ALPHA, read-write
	orphan       *core.Record // a bot with no owner
}

func newCreatorFixture(t *testing.T) creatorFixture {
	t.Helper()
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	teams := core.NewBaseCollection("teams")
	teams.Fields.Add(&core.TextField{Name: "key", Required: true})
	if err := app.Save(teams); err != nil {
		t.Fatal(err)
	}
	members := core.NewAuthCollection("members")
	members.Fields.Add(
		&core.TextField{Name: "name", Required: true},
		&core.SelectField{Name: "kind", Values: []string{"person", "bot"}, MaxSelect: 1},
		&core.RelationField{Name: "teams", CollectionId: teams.Id, MaxSelect: 999},
		&core.SelectField{Name: "scope", Values: []string{"all", "teams"}, MaxSelect: 1, Required: true},
		&core.SelectField{Name: "mode", Values: []string{"rw", "ro"}, MaxSelect: 1, Required: true},
	)
	if err := app.Save(members); err != nil {
		t.Fatal(err)
	}
	members.Fields.Add(
		&core.RelationField{Name: "owner", CollectionId: members.Id, MaxSelect: 1},
		&core.RelationField{Name: "created_by", CollectionId: members.Id, MaxSelect: 1},
	)
	if err := app.Save(members); err != nil {
		t.Fatal(err)
	}
	registerMemberGuards(app)
	registerMemberScopeDefault(app)
	team := func(key string) string {
		r := core.NewRecord(teams)
		r.Set("key", key)
		if err := app.Save(r); err != nil {
			t.Fatal(err)
		}
		return r.Id
	}
	f := creatorFixture{app: app, members: members, alpha: team("ALPHA"), beta: team("BETA")}
	f.human = f.save(t, "boss", "person", "", "", &access{all: true, rw: true})
	f.other = f.save(t, "stranger", "person", "", "", &access{all: true, rw: true})
	f.coord = f.save(t, "bot-coord", botKind, f.human.Id, "", &access{teams: []string{f.alpha}, rw: true})
	f.orphan = f.save(t, "bot-orphan", botKind, "", "", &access{all: true, rw: true})
	return f
}

// create saves a member; a nil access leaves scope and mode to the default.
func (f creatorFixture) create(name, kind, owner, createdBy string, a *access) (*core.Record, error) {
	m := core.NewRecord(f.members)
	m.Set("name", name)
	m.Set("kind", kind)
	m.Set("owner", owner)
	m.Set("created_by", createdBy)
	m.SetEmail(name + "@members.invalid")
	m.SetRandomPassword()
	if a != nil {
		setAccess(m, *a)
	}
	return m, f.app.Save(m)
}

func (f creatorFixture) save(t *testing.T, name, kind, owner, createdBy string, a *access) *core.Record {
	t.Helper()
	m, err := f.create(name, kind, owner, createdBy, a)
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	return m
}

func (f creatorFixture) reload(t *testing.T, m *core.Record) *core.Record {
	t.Helper()
	fresh, err := f.app.FindRecordById("members", m.Id)
	if err != nil {
		t.Fatal(err)
	}
	return fresh
}

func refusedWith(t *testing.T, err error, want string) *router.ApiError {
	t.Helper()
	if err == nil || !strings.Contains(err.Error(), want) {
		t.Fatalf("want a refusal containing %q, got %v", want, err)
	}
	var apiErr *router.ApiError
	errors.As(err, &apiErr)
	return apiErr
}

func TestABotCreatesABotOwnedByItsHumanAndNoWiderThanItself(t *testing.T) {
	f := newCreatorFixture(t)
	w := f.save(t, "bot-w1", botKind, f.human.Id, f.coord.Id, nil)
	// The default is the creator's access, not the (wider) owner's.
	if got := ownAccess(w); got.all || !got.rw || !slices.Equal(got.teams, []string{f.alpha}) {
		t.Fatalf("bot-w1 defaulted to %+v, want ALPHA rw (its creator's)", got)
	}
	if w.GetString("owner") != f.human.Id || w.GetString("created_by") != f.coord.Id {
		t.Fatalf("owner %q created_by %q", w.GetString("owner"), w.GetString("created_by"))
	}
	// Ownership is still one hop: the worker may create a worker in turn.
	f.save(t, "bot-w2", botKind, f.human.Id, w.Id, nil)

	// Wider than the creator: every team, another team, or write over a
	// read-only creator.
	_, err := f.create("bot-wide", botKind, f.human.Id, f.coord.Id, &access{all: true, rw: true})
	if apiErr := refusedWith(t, err, "wider access than bot-coord"); apiErr == nil || apiErr.Data["code"] != "bot_exceeds_owner" {
		t.Fatalf("want code bot_exceeds_owner, got %+v", apiErr)
	}
	_, err = f.create("bot-beta", botKind, f.human.Id, f.coord.Id, &access{teams: []string{f.beta}, rw: true})
	refusedWith(t, err, "wider access than bot-coord")

	// Owned by anyone but the creator's owner, or by nobody.
	_, err = f.create("bot-theirs", botKind, f.other.Id, f.coord.Id, nil)
	refusedWith(t, err, "owned by the creating bot's owner")
	_, err = f.create("bot-loose", botKind, "", f.coord.Id, nil)
	refusedWith(t, err, "owned by the creating bot's owner")
	// created_by names a bot with a human owner, and only a bot records one.
	_, err = f.create("bot-byperson", botKind, f.human.Id, f.human.Id, nil)
	refusedWith(t, err, "created_by names a bot")
	_, err = f.create("bot-byorphan", botKind, f.human.Id, f.orphan.Id, nil)
	refusedWith(t, err, "owned by the creating bot's owner")
	_, err = f.create("person", "person", "", f.coord.Id, nil)
	refusedWith(t, err, "created_by names a bot")
}

func TestABotWithNoHumanOwnerIsRefusedAsBefore(t *testing.T) {
	f := newCreatorFixture(t)
	_, err := f.create("bot-sub", botKind, f.orphan.Id, "", nil)
	refusedWith(t, err, "bot cannot own a bot: bot-orphan is a bot. Create bot-sub with its human owner's token, or with administrator credentials for a bot with no owner")
	// An owned bot naming itself owner is told what to send instead.
	_, err = f.create("bot-self", botKind, f.coord.Id, "", nil)
	refusedWith(t, err, "a bot creates bots for its own owner, boss")
}

// Narrowing a creator narrows what it created, so a worker's token (which the
// coordinator holds) is no way back to access the coordinator lost.
func TestNarrowingTheCreatorNarrowsWhatItCreated(t *testing.T) {
	f := newCreatorFixture(t)
	f.coord.Set("teams", []string{f.alpha, f.beta})
	if err := f.app.Save(f.coord); err != nil {
		t.Fatal(err)
	}
	w := f.save(t, "bot-w1", botKind, f.human.Id, f.coord.Id, nil)
	w2 := f.save(t, "bot-w2", botKind, f.human.Id, w.Id, nil)
	unrelated := f.save(t, "bot-mine", botKind, f.human.Id, "", &access{teams: []string{f.alpha, f.beta}, rw: true})

	f.coord.Set("teams", []string{f.alpha})
	f.coord.Set("mode", "ro")
	if err := f.app.Save(f.coord); err != nil {
		t.Fatal(err)
	}
	for _, m := range []*core.Record{w, w2} {
		got := ownAccess(f.reload(t, m))
		if got.all || got.rw || !slices.Equal(got.teams, []string{f.alpha}) {
			t.Fatalf("%s kept %+v after its creator narrowed to ALPHA ro", m.GetString("name"), got)
		}
	}
	if got := ownAccess(f.reload(t, unrelated)); !got.rw || len(got.teams) != 2 {
		t.Fatalf("a bot the coordinator did not create was narrowed: %+v", got)
	}
	// Widening the worker back past its creator is refused, superuser or not.
	fresh := f.reload(t, w)
	fresh.Set("teams", []string{f.alpha, f.beta})
	refusedWith(t, f.app.Save(fresh), "wider access than bot-coord")
	// Deleting the creator leaves the worker its human's bot.
	if err := f.app.Delete(f.coord); err != nil {
		t.Fatal(err)
	}
	if got := f.reload(t, w); got.GetString("created_by") != "" || got.GetString("owner") != f.human.Id {
		t.Fatalf("after the creator's delete: created_by %q owner %q", got.GetString("created_by"), got.GetString("owner"))
	}
}

// Narrowing the owner leaves the bots' records as they were (the rules cap
// them). A later save of the creator, such as a token rotation, must still
// succeed, and leaves the worker within the owner.
func TestSavingTheCreatorAfterItsOwnerNarrowedStillSaves(t *testing.T) {
	f := newCreatorFixture(t)
	f.coord.Set("scope", "all")
	if err := f.app.Save(f.coord); err != nil {
		t.Fatal(err)
	}
	w := f.save(t, "bot-w1", botKind, f.human.Id, f.coord.Id, nil)
	f.human.Set("scope", "teams")
	f.human.Set("teams", []string{f.alpha})
	if err := f.app.Save(f.human); err != nil {
		t.Fatal(err)
	}
	// Rotating the creator's token saves it with its access unchanged.
	f.coord = f.reload(t, f.coord)
	f.coord.RefreshTokenKey()
	if err := f.app.Save(f.coord); err != nil {
		t.Fatalf("saving the creator after its owner narrowed: %v", err)
	}
	if got := ownAccess(f.reload(t, w)); got.all || !slices.Equal(got.teams, []string{f.alpha}) {
		t.Fatalf("bot-w1 kept %+v, want ALPHA (its owner's)", got)
	}
}

// Revoking a creator must never be refused because of what it created
// (LLL-709 security review): clearing its owner, re-owning it, or deleting
// the human detaches its workers (created_by cleared) and narrows them, and
// the revoking save succeeds.
func TestRevokingTheCreatorDetachesAndNarrowsItsWorkers(t *testing.T) {
	for _, revoke := range []string{"clear owner", "re-own", "delete human"} {
		t.Run(revoke, func(t *testing.T) {
			f := newCreatorFixture(t)
			w := f.save(t, "bot-w1", botKind, f.human.Id, f.coord.Id, nil)
			w2 := f.save(t, "bot-w2", botKind, f.human.Id, w.Id, nil)
			var err error
			switch revoke {
			case "clear owner":
				f.coord.Set("owner", "")
				err = f.app.Save(f.coord)
			case "re-own":
				f.coord.Set("owner", f.other.Id)
				err = f.app.Save(f.coord)
			case "delete human":
				err = f.app.Delete(f.human)
			}
			if err != nil {
				t.Fatalf("%s was refused: %v", revoke, err)
			}
			got := f.reload(t, w)
			if got.GetString("created_by") != "" {
				t.Fatalf("bot-w1 still names its creator after %s", revoke)
			}
			if a := ownAccess(got); a.all || len(a.teams) > 1 || (len(a.teams) == 1 && a.teams[0] != f.alpha) {
				t.Fatalf("bot-w1 widened after %s: %+v", revoke, a)
			}
			if revoke != "delete human" && f.reload(t, w2).GetString("created_by") != w.Id {
				t.Fatalf("bot-w2 lost its creator, which still shares its owner")
			}
		})
	}
}
