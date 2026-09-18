package gopb

import "sync"

// Lisette cannot own package-level state. This lock makes its existing
// environment-backed identity probe a single check/request/remember operation.
var tokenProbeMu sync.Mutex

func LockTokenProbe() { tokenProbeMu.Lock() }

func UnlockTokenProbe() { tokenProbeMu.Unlock() }
