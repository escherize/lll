package gopb

import (
	"sync"
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

// LLL-709 review: rotation by the creating bot.

func (f creatorFixture) tokenWorks(token string) bool {
	_, err := f.app.FindAuthRecordByToken(token, core.TokenTypeAuth)
	return err == nil
}

func (f creatorFixture) mint(t *testing.T, by *core.Record, name string) string {
	t.Helper()
	token, _, err := rotateBot(f.app, by, false, name, 3600)
	if err != nil {
		t.Fatalf("%s rotating %s: %v", by.GetString("name"), name, err)
	}
	if !f.tokenWorks(token) {
		t.Fatalf("control: the token minted for %s does not work", name)
	}
	return token
}

// F2: a bot losing its created_by, by the creator's delete or by a superuser
// clearing it, strands every token the creator minted for it.
func TestLosingTheCreatorStrandsWhatItMinted(t *testing.T) {
	f := newCreatorFixture(t)
	f.save(t, "bot-w1", botKind, f.human.Id, f.coord.Id, nil)
	w2 := f.save(t, "bot-w2", botKind, f.human.Id, f.coord.Id, nil)
	t1 := f.mint(t, f.coord, "bot-w1")
	t2 := f.mint(t, f.coord, "bot-w2")

	w2 = f.reload(t, w2)
	w2.Set("created_by", "")
	if err := f.app.Save(w2); err != nil {
		t.Fatal(err)
	}
	if f.tokenWorks(t2) {
		t.Fatal("a superuser cleared created_by and the creator's token for bot-w2 still works")
	}
	if err := f.app.Delete(f.reload(t, f.coord)); err != nil {
		t.Fatal(err)
	}
	if f.tokenWorks(t1) {
		t.Fatal("the creator was deleted and its token for bot-w1 still works")
	}
}

// F4: a read-only creator rotates nothing.
func TestAReadOnlyCreatorCannotRotate(t *testing.T) {
	f := newCreatorFixture(t)
	f.save(t, "bot-w1", botKind, f.human.Id, f.coord.Id, nil)
	coord := f.reload(t, f.coord)
	coord.Set("mode", "ro")
	if err := f.app.Save(coord); err != nil {
		t.Fatal(err)
	}
	if _, _, err := rotateBot(f.app, f.reload(t, coord), false, "bot-w1", 3600); err == nil {
		t.Fatal("a read-only creator rotated its worker")
	}
}

// F1: a rotation racing the creator's revocation or narrowing never leaves
// a working token wider than what the revocation left. The caller record is
// the one the request authenticated with, as re.Auth is: read before the
// revocation commits.
func TestRotationRacingTheCreatorsRevocation(t *testing.T) {
	for _, revoke := range []string{"clear owner", "narrow"} {
		t.Run(revoke, func(t *testing.T) {
			for round := 0; round < 15; round++ {
				f := newCreatorFixture(t)
				coord := f.reload(t, f.coord)
				coord.Set("teams", []string{f.alpha, f.beta})
				if err := f.app.Save(coord); err != nil {
					t.Fatal(err)
				}
				f.save(t, "bot-w", botKind, f.human.Id, coord.Id, nil)
				stale := f.reload(t, coord)

				var mu sync.Mutex
				var minted []string
				stop := make(chan struct{})
				var wg sync.WaitGroup
				for i := 0; i < 8; i++ {
					wg.Add(1)
					go func() {
						defer wg.Done()
						for {
							select {
							case <-stop:
								return
							default:
							}
							if token, _, err := rotateBot(f.app, stale, false, "bot-w", 3600); err == nil {
								mu.Lock()
								minted = append(minted, token)
								mu.Unlock()
							}
						}
					}()
				}
				fresh := f.reload(t, coord)
				if revoke == "clear owner" {
					fresh.Set("owner", "")
				} else {
					fresh.Set("teams", []string{f.alpha})
				}
				err := f.app.Save(fresh)
				close(stop)
				wg.Wait()
				if err != nil {
					t.Fatalf("round %d: the revocation was refused: %v", round, err)
				}
				w, werr := f.app.FindFirstRecordByFilter("members", "name = 'bot-w'")
				if werr != nil {
					t.Fatal(werr)
				}
				if a := ownAccess(w); revoke == "narrow" && (a.all || len(a.teams) != 1 || a.teams[0] != f.alpha) {
					t.Fatalf("round %d: bot-w kept %+v after the creator was narrowed to ALPHA", round, a)
				}
				if revoke == "clear owner" {
					if w.GetString("created_by") != "" {
						t.Fatalf("round %d: a racing rotation restored created_by", round)
					}
					for _, token := range minted {
						if f.tokenWorks(token) {
							t.Fatalf("round %d: a token the revoked creator minted still works", round)
						}
					}
				}
			}
		})
	}
}
