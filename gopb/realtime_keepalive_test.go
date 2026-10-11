package gopb

import (
	"bufio"
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
	"github.com/pocketbase/pocketbase/tools/subscriptions"
)

var opened = time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)

// LLL-692: every tick puts a keepalive on the channel PocketBase's loop
// reads, which is what resets its idle timer; the client's own messages pass
// through in order.
func TestKeepAliveSendsOnEveryTickAndForwardsMessages(t *testing.T) {
	inner := subscriptions.NewDefaultClient()
	authed(inner, opened.Add(time.Hour))
	c, tick, stop := runKeepAlive(t, inner)
	defer stop()
	for i := 0; i < 3; i++ {
		tick <- opened.Add(time.Duration(i) * time.Minute)
		if got := receive(t, c); got != keepaliveMessage {
			t.Fatalf("tick %d sent %q, want the keepalive", i, got)
		}
	}
	go inner.Send(subscriptions.Message{Name: "issues/abc"})
	if got := receive(t, c); got != "issues/abc" {
		t.Fatalf("forwarded %q, want the record event", got)
	}
}

// A stream whose authenticated subscription lost its auth (a revoked or
// rotated token, LLL-617) closes at the next tick.
func TestKeepAliveClosesAStreamThatLostItsAuth(t *testing.T) {
	inner := subscriptions.NewDefaultClient()
	authed(inner, opened.Add(time.Hour))
	c, tick, stop := runKeepAlive(t, inner)
	defer stop()
	inner.Unset(apis.RealtimeClientAuthKey)
	tick <- opened.Add(time.Minute)
	assertClosed(t, c)
}

// A stream outlives PocketBase's 30 minutes only while its token is valid:
// it closes at the first tick after the token expires.
func TestKeepAliveClosesAStreamWhoseTokenExpired(t *testing.T) {
	inner := subscriptions.NewDefaultClient()
	expiry := opened.Add(2 * time.Hour)
	authed(inner, expiry)
	c, tick, stop := runKeepAlive(t, inner)
	defer stop()
	tick <- expiry.Add(-time.Second)
	if got := receive(t, c); got != keepaliveMessage {
		t.Fatalf("a valid token's stream got %q, want the keepalive", got)
	}
	tick <- expiry
	assertClosed(t, c)
}

// A stream with no authenticated subscription gets no keepalive, so
// PocketBase's idle close still applies, and it never outlives PocketBase's
// 30-minute lifetime.
func TestKeepAliveSendsAGuestStreamNothing(t *testing.T) {
	inner := subscriptions.NewDefaultClient()
	c, tick, stop := runKeepAlive(t, inner)
	defer stop()
	tick <- opened.Add(realtimeGuestLifetime - time.Second)
	select {
	case msg := <-c.Channel():
		t.Fatalf("a guest stream got %q, want nothing", msg.Name)
	case <-time.After(200 * time.Millisecond):
	}
	tick <- opened.Add(realtimeGuestLifetime)
	assertClosed(t, c)
}

// The token is read as PocketBase reads it: a "Bearer " prefix in any case,
// or none (a lowercase "bearer" once closed an authenticated stream at the
// first tick).
func TestBearerTokenMatchesPocketBase(t *testing.T) {
	for header, want := range map[string]string{
		"Bearer abc.def.ghi": "abc.def.ghi",
		"bearer abc.def.ghi": "abc.def.ghi",
		"BEARER abc.def.ghi": "abc.def.ghi",
		"abc.def.ghi":        "abc.def.ghi",
		"Bearer ":            "Bearer ",
	} {
		if got := bearerToken(header); got != want {
			t.Errorf("bearerToken(%q) = %q, want %q", header, got, want)
		}
	}
}

// Discarding the client while the forwarder is blocked handing over a
// keepalive (the loop has ended and nobody reads) neither panics nor leaks:
// the connection's end releases it.
func TestKeepAliveSurvivesADiscardMidTick(t *testing.T) {
	inner := subscriptions.NewDefaultClient()
	authed(inner, opened.Add(time.Hour))
	ctx, cancel := context.WithCancel(context.Background())
	tick := make(chan time.Time)
	c := keepAlive(ctx, inner, opened, tick)
	tick <- opened.Add(time.Minute) // nobody receives the keepalive
	inner.Discard()
	cancel()
	waitFinished(t, c)
}

// A discarded client, with nobody blocked, ends the stream by itself.
func TestKeepAliveEndsWhenTheClientIsDiscarded(t *testing.T) {
	inner := subscriptions.NewDefaultClient()
	c := keepAlive(context.Background(), inner, opened, make(chan time.Time))
	inner.Discard()
	assertClosed(t, c)
	waitFinished(t, c)
}

func authed(client subscriptions.Client, expiry time.Time) {
	client.Set(apis.RealtimeClientAuthKey, &core.Record{})
	client.Set(tokenExpiryKey, expiry)
}

func runKeepAlive(t *testing.T, inner subscriptions.Client) (*keepaliveClient, chan time.Time, func()) {
	ctx, cancel := context.WithCancel(context.Background())
	tick := make(chan time.Time)
	c := keepAlive(ctx, inner, opened, tick)
	return c, tick, func() {
		cancel()
		waitFinished(t, c)
	}
}

func receive(t *testing.T, c *keepaliveClient) string {
	t.Helper()
	select {
	case msg, ok := <-c.Channel():
		if !ok {
			t.Fatal("the stream closed")
		}
		return msg.Name
	case <-time.After(5 * time.Second):
		t.Fatal("no message")
		return ""
	}
}

func assertClosed(t *testing.T, c *keepaliveClient) {
	t.Helper()
	select {
	case msg, ok := <-c.Channel():
		if ok {
			t.Fatalf("got %q, want the stream closed", msg.Name)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the stream stayed open")
	}
}

func waitFinished(t *testing.T, c *keepaliveClient) {
	t.Helper()
	select {
	case <-c.finished:
	case <-time.After(5 * time.Second):
		t.Fatal("the keepalive goroutine did not exit")
	}
}

// Through PocketBase's own realtime route, with its idle timeout shortened:
// an anonymous stream gets no keepalive and closes at the idle timeout, an
// authenticated one (any case of "Bearer") stays open on keepalives, and a
// raw token works too.
func TestKeepAliveOnTheRealtimeRoute(t *testing.T) {
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	defer app.Cleanup()
	const idle = 600 * time.Millisecond
	app.OnRealtimeConnectRequest().BindFunc(func(e *core.RealtimeConnectRequestEvent) error {
		e.IdleTimeout = idle
		return e.Next()
	})
	registerRealtimeKeepalive(app, idle/4)
	r, err := apis.NewRouter(app)
	if err != nil {
		t.Fatal(err)
	}
	mux, err := r.BuildMux()
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(mux)
	// Cleanups run last first: every stream closes before the server waits
	// for its connections.
	t.Cleanup(server.Close)
	user, err := app.FindAuthRecordByEmail("users", "test@example.com")
	if err != nil {
		t.Fatal(err)
	}
	token, err := user.NewAuthToken()
	if err != nil {
		t.Fatal(err)
	}

	guest := openStream(t, server.URL)
	lines, closed := guest.readFor(4 * idle)
	if !closed {
		t.Fatal("an anonymous stream outlived the idle timeout")
	}
	if strings.Contains(lines, "keepalive") {
		t.Fatalf("an anonymous stream got a keepalive: %q", lines)
	}

	for _, auth := range []string{"Bearer " + token, "bearer " + token, token} {
		s := openStream(t, server.URL)
		s.subscribe(t, server.URL, auth, "users/"+user.Id)
		lines, closed := s.readFor(4 * idle)
		if closed {
			t.Fatalf("%q: an authenticated stream closed: %q", auth[:7], lines)
		}
		if !strings.Contains(lines, ": keepalive") {
			t.Fatalf("%q: no keepalive: %q", auth[:7], lines)
		}
	}
}

type stream struct {
	clientID string
	lines    chan string
}

func openStream(t *testing.T, base string) *stream {
	t.Helper()
	resp, err := http.Get(base + "/api/realtime")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { resp.Body.Close() })
	s := &stream{lines: make(chan string)}
	go func() {
		defer close(s.lines)
		scanner := bufio.NewScanner(resp.Body)
		for scanner.Scan() {
			s.lines <- scanner.Text()
		}
	}()
	for line := range s.lines {
		if rest, ok := strings.CutPrefix(line, `data:{"clientId":"`); ok {
			s.clientID = strings.TrimSuffix(rest, `"}`)
			return s
		}
	}
	t.Fatal("no PB_CONNECT")
	return nil
}

func (s *stream) subscribe(t *testing.T, base, auth, topic string) {
	t.Helper()
	body := `{"clientId":"` + s.clientID + `","subscriptions":["` + topic + `"]}`
	req, _ := http.NewRequest(http.MethodPost, base+"/api/realtime", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", auth)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("subscribe: %s", resp.Status)
	}
}

// readFor collects lines for d, or until the stream closes.
func (s *stream) readFor(d time.Duration) (string, bool) {
	var got []string
	deadline := time.After(d)
	for {
		select {
		case line, ok := <-s.lines:
			if !ok {
				return strings.Join(got, "\n"), true
			}
			got = append(got, line)
		case <-deadline:
			return strings.Join(got, "\n"), false
		}
	}
}
