package gopb

import (
	"errors"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/subscriptions"
)

// LLL-692: an idle realtime stream must stay open. PocketBase closes a
// realtime connection that has carried no message for 5 minutes (its
// IdleTimeout) and any connection after 30 minutes (its MaxTimeout), so an
// idle `lll watch` and the board's own subscription dropped and reconnected
// every five minutes, printing "stream lost" each time.
//
// The server now sends a keepalive every realtimeKeepalive: an SSE comment
// line, which every SSE reader (lll's FrameParser included, since 1.0) skips.
// It travels through the client's own message channel, so PocketBase's
// connection loop writes it and resets the idle timer; nothing else writes
// to the response concurrently. The keepalive also keeps proxies that close
// silent connections (Fly's, a reverse proxy in front of `lll up`) from
// cutting the stream.
//
// The 5-minute reconnect was also what bounded a revoked token's silence
// (LLL-617): PocketBase clears a client's auth when its token is revoked but
// keeps the stream open, and that stream carries no event again. The CLI
// notices only when it reconnects. So the same tick closes a stream whose
// auth was cleared, and the client's reconnect check names the dead token
// within one interval instead of five minutes.
const (
	realtimeKeepalive   = 30 * time.Second
	realtimeMaxLifetime = 24 * time.Hour

	keepaliveMessage = "LLL_KEEPALIVE"
	authLostMessage  = "LLL_AUTH_LOST"

	// subscribedAuthedKey marks, in the client's store, a client whose
	// subscription carried a valid token.
	subscribedAuthedKey = "lll_subscribed_authed"
)

var errRealtimeAuthLost = errors.New("realtime client lost its auth")

func registerRealtimeKeepalive(app core.App) {
	app.OnRealtimeConnectRequest().BindFunc(func(e *core.RealtimeConnectRequestEvent) error {
		// The keepalive resets the idle timer; the lifetime cap stays, a day
		// rather than half an hour, so a long watch reconnects daily at most.
		e.MaxTimeout = realtimeMaxLifetime
		done := e.Request.Context().Done()
		go func() {
			ticker := time.NewTicker(realtimeKeepalive)
			defer ticker.Stop()
			keepAlive(e.Client, done, ticker.C)
		}()
		return e.Next()
	})

	app.OnRealtimeSubscribeRequest().BindFunc(func(e *core.RealtimeSubscribeRequestEvent) error {
		if err := e.Next(); err != nil {
			return err
		}
		if e.Auth != nil {
			e.Client.Set(subscribedAuthedKey, true)
		}
		return nil
	})

	app.OnRealtimeMessageSend().BindFunc(func(e *core.RealtimeMessageEvent) error {
		switch e.Message.Name {
		case keepaliveMessage:
			if _, err := e.Response.Write([]byte(": keepalive\n\n")); err != nil {
				return err
			}
			return e.Flush()
		case authLostMessage:
			// An error ends PocketBase's connection loop, which closes the
			// stream; the client reconnects and its token check reports.
			return errRealtimeAuthLost
		}
		return e.Next()
	})
}

// keepAlive sends a keepalive to client on every tick until done, or the
// auth-lost message once a client that subscribed with a valid token has had
// its auth cleared. Send blocks until the connection loop takes the message;
// when the loop has ended, PocketBase discards the client, closing its
// channel, and Send returns.
func keepAlive(client subscriptions.Client, done <-chan struct{}, tick <-chan time.Time) {
	for {
		select {
		case <-done:
			return
		case <-tick:
			auth, _ := client.Get(apis.RealtimeClientAuthKey).(*core.Record)
			if client.Get(subscribedAuthedKey) == true && auth == nil {
				client.Send(subscriptions.Message{Name: authLostMessage})
				return
			}
			client.Send(subscriptions.Message{Name: keepaliveMessage})
		}
	}
}
