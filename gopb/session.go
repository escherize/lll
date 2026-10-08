package gopb

import "sync"

// Session is one lll process's live credential state for its pb.Client
// (LLL-486). Lisette cannot own mutable package state, and this state changes
// after construction: lll up swaps its boot token for the board's member
// token, a board renewal re-mints it, and the identity probe remembers which
// token it already checked. It used to live in the process environment
// (LLL_TOKEN, LLL_TOKEN_PROBED, LLL_REALTIME_SUBSCRIPTION), where every child
// process inherited it. A Session is created by its owner and passed down;
// nothing reaches it ambiently.
//
// A Session is a handle: copies share one state, which is what lets every
// copy of a pb.Client see a renewal. Its methods take the handle by value so
// a read-only Lisette value can still renew.
type Session struct{ s *sessionState }

type sessionState struct {
	mu           sync.Mutex
	probeMu      sync.Mutex
	token        string
	probed       string
	subscription string
}

// NewSession starts a session holding token ("" for none).
func NewSession(token string) Session { return Session{s: &sessionState{token: token}} }

// Token is the credential every request of this session sends.
func (h Session) Token() string {
	h.s.mu.Lock()
	defer h.s.mu.Unlock()
	return h.s.token
}

// SetToken replaces the credential (a renewal, or a boot handing over).
func (h Session) SetToken(token string) {
	h.s.mu.Lock()
	defer h.s.mu.Unlock()
	h.s.token = token
}

// Probed is the fingerprint of the token the server last confirmed.
func (h Session) Probed() string {
	h.s.mu.Lock()
	defer h.s.mu.Unlock()
	return h.s.probed
}

// SetProbed records (or, with "", forgets) the confirmed fingerprint.
func (h Session) SetProbed(key string) {
	h.s.mu.Lock()
	defer h.s.mu.Unlock()
	h.s.probed = key
}

// Subscription is the board's accepted realtime subscription request, kept
// so a renewal can re-authenticate that same client (LLL-445).
func (h Session) Subscription() string {
	h.s.mu.Lock()
	defer h.s.mu.Unlock()
	return h.s.subscription
}

// SetSubscription records the accepted realtime subscription request.
func (h Session) SetSubscription(payload string) {
	h.s.mu.Lock()
	defer h.s.mu.Unlock()
	h.s.subscription = payload
}

// LockProbe makes the identity probe one check/request/remember operation,
// so concurrent empty reads coalesce into a single probe.
func (h Session) LockProbe() { h.s.probeMu.Lock() }

// UnlockProbe releases LockProbe.
func (h Session) UnlockProbe() { h.s.probeMu.Unlock() }
