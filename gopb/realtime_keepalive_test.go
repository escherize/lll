package gopb

import (
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/subscriptions"
)

// LLL-692: every tick puts a keepalive on the client's channel, which is what
// resets PocketBase's idle timer.
func TestKeepAliveSendsOnEveryTick(t *testing.T) {
	client := subscriptions.NewDefaultClient()
	done, tick, finished := runKeepAlive(client)
	defer close(done)
	for i := 0; i < 3; i++ {
		tick <- time.Now()
		if got := receive(t, client); got != keepaliveMessage {
			t.Fatalf("tick %d sent %q, want the keepalive", i, got)
		}
	}
	select {
	case <-finished:
		t.Fatal("keepAlive returned while the connection was open")
	default:
	}
}

// A stream whose auth was cleared after a subscription set it (a revoked
// token, LLL-617) is told to close, and the keepalive stops.
func TestKeepAliveClosesAStreamThatLostItsAuth(t *testing.T) {
	client := subscriptions.NewDefaultClient()
	client.Set(apis.RealtimeClientAuthKey, &core.Record{})
	client.Set(subscribedAuthedKey, true)
	done, tick, finished := runKeepAlive(client)
	defer close(done)

	tick <- time.Now()
	if got := receive(t, client); got != keepaliveMessage {
		t.Fatalf("an authenticated stream got %q, want the keepalive", got)
	}
	client.Unset(apis.RealtimeClientAuthKey)
	tick <- time.Now()
	if got := receive(t, client); got != authLostMessage {
		t.Fatalf("a stream that lost its auth got %q, want the close", got)
	}
	waitFinished(t, finished)
}

// A guest stream, never authenticated, is not closed: there was no token
// to lose.
func TestKeepAliveLeavesAGuestStreamOpen(t *testing.T) {
	client := subscriptions.NewDefaultClient()
	client.Set(apis.RealtimeClientAuthKey, (*core.Record)(nil))
	done, tick, _ := runKeepAlive(client)
	defer close(done)
	for i := 0; i < 2; i++ {
		tick <- time.Now()
		if got := receive(t, client); got != keepaliveMessage {
			t.Fatalf("a guest stream got %q, want the keepalive", got)
		}
	}
}

// The keepalive ends with the connection.
func TestKeepAliveStopsWithTheConnection(t *testing.T) {
	done, _, finished := runKeepAlive(subscriptions.NewDefaultClient())
	close(done)
	waitFinished(t, finished)
}

func runKeepAlive(client subscriptions.Client) (chan struct{}, chan time.Time, chan struct{}) {
	done := make(chan struct{})
	tick := make(chan time.Time)
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		keepAlive(client, done, tick)
	}()
	return done, tick, finished
}

func receive(t *testing.T, client subscriptions.Client) string {
	t.Helper()
	select {
	case msg := <-client.Channel():
		return msg.Name
	case <-time.After(5 * time.Second):
		t.Fatal("no message")
		return ""
	}
}

func waitFinished(t *testing.T, finished chan struct{}) {
	t.Helper()
	select {
	case <-finished:
	case <-time.After(5 * time.Second):
		t.Fatal("keepAlive did not return")
	}
}
