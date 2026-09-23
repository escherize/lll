package gopb

import (
	"net/http"
	"sync"

	"github.com/pocketbase/pocketbase/core"
)

// API file modifiers are resolved from a record read before Save. Lock the
// whole request for one issue so concurrent append/remove requests cannot
// replace another request's successful files. Entries live only while held
// or awaited; requests for different issues remain independent.
type issueWriteLocks struct {
	mu      sync.Mutex
	entries map[string]*issueWriteLock
}

type issueWriteLock struct {
	mu   sync.Mutex
	refs int
}

func (locks *issueWriteLocks) acquire(id string) func() {
	locks.mu.Lock()
	if locks.entries == nil {
		locks.entries = make(map[string]*issueWriteLock)
	}
	entry := locks.entries[id]
	if entry == nil {
		entry = &issueWriteLock{}
		locks.entries[id] = entry
	}
	entry.refs++
	locks.mu.Unlock()
	entry.mu.Lock()
	return func() {
		entry.mu.Unlock()
		locks.mu.Lock()
		entry.refs--
		if entry.refs == 0 {
			delete(locks.entries, id)
		}
		locks.mu.Unlock()
	}
}

// serializeRecordUpdates holds a record's lock across a whole PATCH or DELETE
// of an issue or a doc. Relation modifiers ("issues+", "labels-") are
// resolved the same way as file modifiers: PocketBase reads the record, applies
// the modifier in memory, and saves the whole array. Without the lock,
// sixteen concurrent "issues+" PATCHes to one doc kept as few as one edge
// (LLL-513). One process owns the database, so an in-process lock is enough.
// PocketBase ids are per collection. A cross-collection collision only makes
// two requests wait for each other.
func serializeRecordUpdates(locks *issueWriteLocks) func(*core.RequestEvent) error {
	return func(re *core.RequestEvent) error {
		if re.Request.Method == http.MethodPatch || re.Request.Method == http.MethodDelete {
			if id := re.Request.PathValue("id"); id != "" {
				collection, err := re.App.FindCachedCollectionByNameOrId(re.Request.PathValue("collection"))
				if err == nil && (collection.Name == "issues" || collection.Name == "docs") {
					unlock := locks.acquire(id)
					defer unlock()
				}
			}
		}
		return re.Next()
	}
}
