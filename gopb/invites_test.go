package gopb

import (
	"errors"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

type inviteFixture struct {
	app         core.App
	alpha, beta string
	full        *core.Record // all + rw
	scoped      *core.Record // ALPHA + rw
	reader      *core.Record // ALPHA + ro
}

func newInviteFixture(t *testing.T) inviteFixture {
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
	members.AddIndex("idx_members_name_test", true, "name", "")
	if err := app.Save(members); err != nil {
		t.Fatal(err)
	}
	members.Fields.Add(&core.RelationField{Name: "owner", CollectionId: members.Id, MaxSelect: 1})
	if err := app.Save(members); err != nil {
		t.Fatal(err)
	}
	invites := core.NewBaseCollection("invites")
	invites.Fields.Add(
		&core.TextField{Name: "code_hash", Required: true, Hidden: true},
		&core.RelationField{Name: "teams", CollectionId: teams.Id, MaxSelect: 999, Hidden: true},
		&core.SelectField{Name: "mode", Values: []string{"ro", "rw"}, MaxSelect: 1, Required: true, Hidden: true},
		&core.DateField{Name: "expires", Required: true, Hidden: true},
		&core.RelationField{Name: "creator", CollectionId: members.Id, MaxSelect: 1, Hidden: true},
		&core.BoolField{Name: "superuser", Hidden: true},
		&core.DateField{Name: "redeemed", Hidden: true},
		&core.RelationField{Name: "redeemed_by", CollectionId: members.Id, MaxSelect: 1, Hidden: true},
	)
	invites.AddIndex("idx_invites_code_hash", true, "code_hash", "")
	if err := app.Save(invites); err != nil {
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
	f := inviteFixture{app: app, alpha: team("ALPHA"), beta: team("BETA")}
	member := func(name string, a access) *core.Record {
		m := core.NewRecord(members)
		m.Set("name", name)
		m.Set("kind", "person")
		m.SetEmail(name + "@members.invalid")
		m.SetRandomPassword()
		setAccess(m, a)
		if err := app.Save(m); err != nil {
			t.Fatal(err)
		}
		return m
	}
	f.full = member("owner", access{all: true, rw: true})
	f.scoped = member("guest", access{teams: []string{f.alpha}, rw: true})
	f.reader = member("reader", access{teams: []string{f.alpha}})
	return f
}

func (f inviteFixture) mint(t *testing.T, creator *core.Record, g inviteGrant, now time.Time) string {
	t.Helper()
	code, _, err := createInvite(f.app, creator, g, now)
	if err != nil {
		t.Fatal(err)
	}
	return code
}

func TestInviteCodesAreLongRandomAndHashed(t *testing.T) {
	f := newInviteFixture(t)
	seen := map[string]bool{}
	for range 50 {
		code, invite, err := createInvite(f.app, nil, inviteGrant{teams: []string{f.alpha}}, time.Now())
		if err != nil {
			t.Fatal(err)
		}
		if !wellFormedCode(code) || seen[code] {
			t.Fatalf("code %q is malformed or repeated", code)
		}
		seen[code] = true
		if invite.GetString("code_hash") != inviteCodeHash(code) || strings.Contains(invite.GetString("code_hash"), code) {
			t.Fatal("the invite must store the code's hash, never the code")
		}
	}
}

func TestAnInviteCannotGrantMoreThanItsCreatorHolds(t *testing.T) {
	f := newInviteFixture(t)
	cases := []struct {
		name    string
		creator *core.Record
		grant   inviteGrant
		want    bool
	}{
		{"full creator, any team, rw", f.full, inviteGrant{teams: []string{f.alpha, f.beta}, rw: true}, true},
		{"scoped rw creator, own team, rw", f.scoped, inviteGrant{teams: []string{f.alpha}, rw: true}, true},
		{"scoped rw creator, own team, ro", f.scoped, inviteGrant{teams: []string{f.alpha}}, true},
		{"scoped rw creator, a team it cannot see", f.scoped, inviteGrant{teams: []string{f.beta}}, false},
		{"scoped rw creator, own team plus another", f.scoped, inviteGrant{teams: []string{f.alpha, f.beta}}, false},
		{"read-only creator, rw invite", f.reader, inviteGrant{teams: []string{f.alpha}, rw: true}, false},
		{"read-only creator, ro invite", f.reader, inviteGrant{teams: []string{f.alpha}}, false},
		{"no teams", f.full, inviteGrant{rw: true}, false},
	}
	for _, c := range cases {
		if got := grantAllowed(effectiveAccess(f.app, c.creator), c.grant); got != c.want {
			t.Errorf("%s: grantAllowed = %v, want %v", c.name, got, c.want)
		}
	}
	// The route's team check answers a hidden team like a missing one.
	if _, err := inviteTeamIDs(f.app, effectiveAccess(f.app, f.scoped), []string{f.beta}); err == nil {
		t.Error("a scoped creator named a team it cannot see")
	}
	if _, err := inviteTeamIDs(f.app, effectiveAccess(f.app, f.scoped), []string{"nosuchteam00001"}); err == nil {
		t.Error("an unknown team id was accepted")
	}
	if ids, err := inviteTeamIDs(f.app, effectiveAccess(f.app, f.scoped), []string{f.alpha, f.alpha}); err != nil || len(ids) != 1 {
		t.Errorf("duplicates should collapse: %v %v", ids, err)
	}
}

func TestRedeemingCreatesAMemberWithExactlyTheInvitesGrants(t *testing.T) {
	f := newInviteFixture(t)
	now := time.Now()
	code := f.mint(t, f.scoped, inviteGrant{teams: []string{f.alpha}}, now)
	m, err := redeemInvite(f.app, code, "  Visitor ", now)
	if err != nil {
		t.Fatal(err)
	}
	got, err := f.app.FindRecordById("members", m.Id)
	if err != nil {
		t.Fatal(err)
	}
	if got.GetString("name") != "Visitor" || got.GetString("kind") != "person" || got.GetString("owner") != "" ||
		got.GetString("scope") != "teams" || !slices.Equal(got.GetStringSlice("teams"), []string{f.alpha}) ||
		got.GetString("mode") != "ro" {
		t.Fatalf("joined member has the wrong grants: %v", got.PublicExport())
	}
	if !strings.HasSuffix(got.Email(), "@members.invalid") {
		t.Fatalf("joined member email should be synthesized: %q", got.Email())
	}
	token, err := got.NewStaticAuthToken(joinedTokenLifetime)
	if err != nil {
		t.Fatal(err)
	}
	if back, err := f.app.FindAuthRecordByToken(token, core.TokenTypeAuth); err != nil || back.Id != got.Id {
		t.Fatalf("the joined member's token does not authenticate it: %v", err)
	}
	invite, err := f.app.FindFirstRecordByData("invites", "code_hash", inviteCodeHash(code))
	if err != nil {
		t.Fatal(err)
	}
	if invite.GetDateTime("redeemed").IsZero() || invite.GetString("redeemed_by") != got.Id {
		t.Fatalf("the invite is not marked redeemed: %v", invite.FieldsData())
	}
}

func TestRedeemRefusalsNameTheFix(t *testing.T) {
	f := newInviteFixture(t)
	now := time.Now()
	code := f.mint(t, f.full, inviteGrant{teams: []string{f.alpha}, rw: true}, now)
	if _, err := redeemInvite(f.app, code, "first", now); err != nil {
		t.Fatal(err)
	}
	stale := f.mint(t, f.full, inviteGrant{teams: []string{f.alpha}}, now.Add(-8*24*time.Hour))
	unknown, _, _ := newInviteCode()
	for _, c := range []struct {
		name, code string
		want       error
	}{
		{"second redemption", code, errInviteUsed},
		{"expired", stale, errInviteExpired},
		{"unknown", unknown, errInviteUnknown},
		{"malformed", "abc", errInviteUnknown},
		{"empty", "", errInviteUnknown},
	} {
		_, err := redeemInvite(f.app, c.code, "second", now)
		if !errors.Is(err, c.want) {
			t.Errorf("%s: got %v, want %v", c.name, err, c.want)
			continue
		}
		if !strings.Contains(err.Error(), "Ask whoever invited you for a new link") &&
			!strings.Contains(err.Error(), "ask whoever invited you for a new link") {
			t.Errorf("%s: the refusal names no fix: %v", c.name, err)
		}
	}
	if _, err := f.app.FindFirstRecordByData("members", "name", "second"); err == nil {
		t.Error("a refused redemption created a member")
	}
}

func TestARefusedNameLeavesTheCodeAlive(t *testing.T) {
	f := newInviteFixture(t)
	now := time.Now()
	code := f.mint(t, f.full, inviteGrant{teams: []string{f.alpha}}, now)
	for _, name := range []string{"owner", "OWNER", "bot-x", "Bot-x", "", "   ", "<script>", "a\nb", "é", strings.Repeat("a", 41), "Bryan  Maass", "owner.", "_owner", "a--b"} {
		if _, err := redeemInvite(f.app, code, name, now); err == nil {
			t.Fatalf("name %q was accepted", name)
		}
	}
	if _, err := redeemInvite(f.app, code, "newcomer", now); err != nil {
		t.Fatalf("the code died with a refused name: %v", err)
	}
	owner, err := f.app.FindRecordById("members", f.full.Id)
	if err != nil || owner.GetString("scope") != "all" || owner.Email() != "owner@members.invalid" {
		t.Fatal("an existing member was touched by a colliding redemption")
	}
}

func TestConcurrentRedemptionsYieldExactlyOneMember(t *testing.T) {
	f := newInviteFixture(t)
	now := time.Now()
	code := f.mint(t, f.full, inviteGrant{teams: []string{f.alpha}}, now)
	const n = 16
	var wg sync.WaitGroup
	errs := make([]error, n)
	for i := range n {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, errs[i] = redeemInvite(f.app, code, "racer"+string(rune('a'+i)), now)
		}()
	}
	wg.Wait()
	wins := 0
	for _, err := range errs {
		switch {
		case err == nil:
			wins++
		case !errors.Is(err, errInviteUsed):
			t.Errorf("unexpected refusal: %v", err)
		}
	}
	joined, err := f.app.FindRecordsByFilter("members", "name ~ 'racer'", "", 0, 0)
	if err != nil {
		t.Fatal(err)
	}
	if wins != 1 || len(joined) != 1 {
		t.Fatalf("%d redemptions succeeded and %d members exist; want exactly 1", wins, len(joined))
	}
}

func TestNarrowingTheCreatorVoidsItsUnredeemedInvites(t *testing.T) {
	f := newInviteFixture(t)
	now := time.Now()
	code := f.mint(t, f.scoped, inviteGrant{teams: []string{f.alpha}, rw: true}, now)
	setAccess(f.scoped, access{teams: []string{f.alpha}})
	if err := f.app.Save(f.scoped); err != nil {
		t.Fatal(err)
	}
	if _, err := redeemInvite(f.app, code, "late", now); !errors.Is(err, errInviteVoid) {
		t.Fatalf("got %v, want the void refusal", err)
	}
}

func TestDeletingTheJoinedMemberDoesNotReviveTheCode(t *testing.T) {
	f := newInviteFixture(t)
	now := time.Now()
	code := f.mint(t, f.full, inviteGrant{teams: []string{f.alpha}}, now)
	m, err := redeemInvite(f.app, code, "leaver", now)
	if err != nil {
		t.Fatal(err)
	}
	if err := f.app.Delete(m); err != nil {
		t.Fatal(err)
	}
	if _, err := redeemInvite(f.app, code, "again", now); !errors.Is(err, errInviteUsed) {
		t.Fatalf("got %v, want the used refusal", err)
	}
}

func TestABotCannotInvitePeople(t *testing.T) {
	f := newInviteFixture(t)
	now := time.Now()
	members, err := f.app.FindCollectionByNameOrId("members")
	if err != nil {
		t.Fatal(err)
	}
	bot := core.NewRecord(members)
	bot.Set("name", "bot-helper")
	bot.Set("kind", "bot")
	bot.Set("owner", f.full.Id)
	bot.SetEmail("bot-helper@members.invalid")
	bot.SetRandomPassword()
	if err := f.app.Save(bot); err != nil {
		t.Fatal(err)
	}
	// Minted directly (the route refuses a bot before this point): the
	// redemption check must refuse it on its own.
	code := f.mint(t, bot, inviteGrant{teams: []string{f.alpha}}, now)
	if _, err := redeemInvite(f.app, code, "via-bot", now); !errors.Is(err, errInviteVoid) {
		t.Fatalf("got %v, want the void refusal", err)
	}
}

// An owned person (owner set by a superuser) is refused like a bot: the
// people it invited would have no owner, so narrowing its owner would not
// reach them.
func TestAnOwnedPersonCannotInvitePeople(t *testing.T) {
	f := newInviteFixture(t)
	now := time.Now()
	members, err := f.app.FindCollectionByNameOrId("members")
	if err != nil {
		t.Fatal(err)
	}
	owned := core.NewRecord(members)
	owned.Set("name", "ownedp")
	owned.Set("kind", "person")
	owned.Set("owner", f.full.Id)
	owned.SetEmail("ownedp@members.invalid")
	owned.SetRandomPassword()
	setAccess(owned, access{teams: []string{f.alpha}, rw: true})
	if err := f.app.Save(owned); err != nil {
		t.Fatal(err)
	}
	if mayInvite(owned) || !mayInvite(f.scoped) {
		t.Fatal("mayInvite must refuse exactly members with an owner or of kind bot")
	}
	code := f.mint(t, owned, inviteGrant{teams: []string{f.alpha}, rw: true}, now)
	if _, err := redeemInvite(f.app, code, "via-owned", now); !errors.Is(err, errInviteVoid) {
		t.Fatalf("got %v, want the void refusal", err)
	}
}
