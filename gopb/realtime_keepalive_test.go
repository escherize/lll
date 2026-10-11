package gopb

import (
	"context"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
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

// A stream that never authenticated keeps PocketBase's 30-minute lifetime.
func TestKeepAliveClosesAGuestStreamAtPocketBasesLifetime(t *testing.T) {
	inner := subscriptions.NewDefaultClient()
	c, tick, stop := runKeepAlive(t, inner)
	defer stop()
	tick <- opened.Add(realtimeGuestLifetime - time.Second)
	if got := receive(t, c); got != keepaliveMessage {
		t.Fatalf("a young guest stream got %q, want the keepalive", got)
	}
	tick <- opened.Add(realtimeGuestLifetime)
	assertClosed(t, c)
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
