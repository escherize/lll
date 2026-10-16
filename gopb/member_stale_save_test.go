package gopb

import (
	"sync"
	"sync/atomic"
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

// LLL-709 review F5 / LLL-713: PocketBase's update handler loads a record
// before its transaction and Save writes every column, so a member's own
// PATCH (a bot may PATCH itself) saved a stale copy over a committed
// narrowing, detach or token rotation.

// staleSave is the records API's update: the record as loaded at the start
// of the request, one harmless field changed, saved in a transaction.
func staleSave(app core.App, stale *core.Record) error {
	stale.Set("emailVisibility", !stale.GetBool("emailVisibility"))
	return app.RunInTransaction(func(tx core.App) error { return tx.Save(stale) })
}

func TestAStaleSelfSaveKeepsACommittedNarrowing(t *testing.T) {
	f := newCreatorFixture(t)
	coord := f.reload(t, f.coord)
	coord.Set("teams", []string{f.alpha, f.beta})
	if err := f.app.Save(coord); err != nil {
		t.Fatal(err)
	}
	w := f.save(t, "bot-w", botKind, f.human.Id, coord.Id, nil)
	stale := f.reload(t, w)
	coord = f.reload(t, coord)
	coord.Set("teams", []string{f.alpha})
	if err := f.app.Save(coord); err != nil {
		t.Fatal(err)
	}
	if err := staleSave(f.app, stale); err != nil {
		t.Fatal(err)
	}
	if a := ownAccess(f.reload(t, w)); a.all || len(a.teams) != 1 || a.teams[0] != f.alpha {
		t.Fatalf("a stale self-save undid the creator's narrowing: %+v", a)
	}
	if f.reload(t, w).GetBool("emailVisibility") == w.GetBool("emailVisibility") {
		t.Fatal("control: the self-save's own field was not written")
	}
}

func TestAStaleSelfSaveKeepsACommittedRotationAndDetach(t *testing.T) {
	f := newCreatorFixture(t)
	f.save(t, "bot-w", botKind, f.human.Id, f.coord.Id, nil)
	leaked := f.mint(t, f.coord, "bot-w")
	stale, err := f.app.FindFirstRecordByFilter("members", "name = 'bot-w'")
	if err != nil {
		t.Fatal(err)
	}
	// The owner rotates the leaked token away.
	if _, _, err := rotateBot(f.app, f.human, false, "bot-w", 3600); err != nil {
		t.Fatal(err)
	}
	if err := staleSave(f.app, stale); err != nil {
		t.Fatal(err)
	}
	if f.tokenWorks(leaked) {
		t.Fatal("a stale self-save restored the token key the owner rotated away")
	}
	// A committed detach survives a stale self-save too.
	stale, _ = f.app.FindFirstRecordByFilter("members", "name = 'bot-w'")
	coord := f.reload(t, f.coord)
	coord.Set("owner", "")
	if err := f.app.Save(coord); err != nil {
		t.Fatal(err)
	}
	if err := staleSave(f.app, stale); err != nil {
		t.Fatal(err)
	}
	if got, _ := f.app.FindFirstRecordByFilter("members", "name = 'bot-w'"); got.GetString("created_by") != "" {
		t.Fatal("a stale self-save restored created_by after the detach")
	}
}

// The race itself: self-saves from goroutines that each load the record and
// save it, against the owner rotating. Every rotation must strand the token
// it replaced. Counts both sides so a pass is not vacuous.
func TestConcurrentSelfSavesNeverRestoreARotatedToken(t *testing.T) {
	f := newCreatorFixture(t)
	f.save(t, "bot-w", botKind, f.human.Id, f.coord.Id, nil)
	var saves atomic.Int64
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
				stale, err := f.app.FindFirstRecordByFilter("members", "name = 'bot-w'")
				if err == nil && staleSave(f.app, stale) == nil {
					saves.Add(1)
				}
			}
		}()
	}
	var stranded []string
	for i := 0; i < 40; i++ {
		token, _, err := rotateBot(f.app, f.human, false, "bot-w", 3600)
		if err != nil {
			t.Fatal(err)
		}
		stranded = append(stranded, token)
	}
	close(stop)
	wg.Wait()
	if saves.Load() == 0 {
		t.Fatal("control: no self-save ran")
	}
	live := 0
	for _, token := range stranded[:len(stranded)-1] {
		if f.tokenWorks(token) {
			live++
		}
	}
	if live > 0 {
		t.Fatalf("%d of %d rotated-away tokens still work after %d racing self-saves", live, len(stranded)-1, saves.Load())
	}
	if !f.tokenWorks(stranded[len(stranded)-1]) {
		t.Fatal("control: the last rotation's token does not work")
	}
}
