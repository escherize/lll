package gopb

import "sync"

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
