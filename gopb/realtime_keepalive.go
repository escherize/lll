package gopb

import (
	"context"
	"strings"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/security"
	"github.com/pocketbase/pocketbase/tools/subscriptions"
	"github.com/spf13/cast"
)

// LLL-692: an idle realtime stream must stay open. PocketBase closes a
// realtime connection that has carried no message for 5 minutes (its
// IdleTimeout) and any connection after 30 minutes (its MaxTimeout), so an
// idle `lll watch` and the board's own subscription dropped and reconnected
// every five minutes, printing "stream lost" each time.
//
// The server now sends a keepalive every realtimeKeepalive: an SSE comment
// line, which every SSE reader (lll's FrameParser included, since 1.0) skips.
// It reaches PocketBase's connection loop as a message, so the loop writes it
// and resets its idle timer; nothing else writes to the response. It also
// keeps proxies that close silent connections (Fly's, a reverse proxy in
// front of `lll up`) from cutting the stream.
//
// The 5-minute and 30-minute closes were also what ended a stream whose token
// had died. A stream's authorization is checked when it subscribes, and
// PocketBase clears it when the token is revoked or rotated but keeps the
// stream open, while an expired token's stream keeps receiving events. So a
// stream now lives past PocketBase's 30 minutes only while its token is
// valid: each tick closes a stream whose subscription was authenticated and
// whose auth was cleared or whose token has expired, and a stream that never
// authenticated still closes at 30 minutes. The client's reconnect check
// then names the dead token.
const (
	realtimeKeepalive = 30 * time.Second
	// The hard cap; within it, a stream lives only while its token does.
	realtimeMaxLifetime = 24 * time.Hour
	// PocketBase's own MaxTimeout, kept for a stream with no token.
	realtimeGuestLifetime = 30 * time.Minute

	keepaliveMessage = "LLL_KEEPALIVE"

	// tokenExpiryKey holds, in the client's store, the expiry of the token
	// the client's latest authenticated subscription carried.
	tokenExpiryKey = "lll_token_expiry"
)

func registerRealtimeKeepalive(app core.App) {
	app.OnRealtimeConnectRequest().BindFunc(func(e *core.RealtimeConnectRequestEvent) error {
		e.MaxTimeout = realtimeMaxLifetime
		ctx, cancel := context.WithCancel(e.Request.Context())
		ticker := time.NewTicker(realtimeKeepalive)
		client := keepAlive(ctx, e.Client, time.Now(), ticker.C)
		e.Client = client
		err := e.Next()
		// The connection loop has ended: stop the forwarder and wait for it,
		// so no goroutine outlives the connection.
		cancel()
		ticker.Stop()
		<-client.finished
		return err
	})

	app.OnRealtimeSubscribeRequest().BindFunc(func(e *core.RealtimeSubscribeRequestEvent) error {
		if err := e.Next(); err != nil {
			return err
		}
		if e.Auth == nil {
			e.Client.Unset(tokenExpiryKey)
			return nil
		}
		// PocketBase loaded e.Auth from this token, so its signature is
		// already checked; only its exp is read here.
		token := strings.TrimPrefix(e.Request.Header.Get("Authorization"), "Bearer ")
		claims, err := security.ParseUnverifiedJWT(token)
		exp := cast.ToInt64(claims["exp"])
		if err != nil || exp <= 0 {
			// No readable expiry: treat the stream as expiring now, so it
			// closes at the next tick rather than outliving its token.
			e.Client.Set(tokenExpiryKey, time.Now())
			return nil
		}
		e.Client.Set(tokenExpiryKey, time.Unix(exp, 0))
		return nil
	})

	app.OnRealtimeMessageSend().BindFunc(func(e *core.RealtimeMessageEvent) error {
		if e.Message.Name != keepaliveMessage {
			return e.Next()
		}
		if _, err := e.Response.Write([]byte(": keepalive\n\n")); err != nil {
			return err
		}
		return e.Flush()
	})
}

// keepaliveClient is the realtime client with its message channel replaced:
// PocketBase's connection loop reads Channel(), which carries the client's
// own messages, in order, plus a keepalive on every tick. One goroutine owns
// that channel: it only receives from the client's channel and sends on its
// own, so it never sends on a channel PocketBase may close, and closing its
// channel is how it ends the stream.
type keepaliveClient struct {
	subscriptions.Client
	out      chan subscriptions.Message
	finished chan struct{}
}

func (c *keepaliveClient) Channel() chan subscriptions.Message { return c.out }

// keepAlive wraps client and starts its forwarder, which runs until ctx ends,
// the client is discarded, or a tick finds the stream should close (see
// streamExpired). opened is when the connection started; each tick's time is
// the check's "now".
func keepAlive(ctx context.Context, client subscriptions.Client, opened time.Time, tick <-chan time.Time) *keepaliveClient {
	c := &keepaliveClient{Client: client, out: make(chan subscriptions.Message), finished: make(chan struct{})}
	go func() {
		defer close(c.finished)
		defer close(c.out)
		in := client.Channel()
		for {
			var msg subscriptions.Message
			select {
			case <-ctx.Done():
				return
			case m, ok := <-in:
				if !ok {
					return
				}
				msg = m
			case now := <-tick:
				if streamExpired(client, opened, now) {
					return
				}
				msg = subscriptions.Message{Name: keepaliveMessage}
			}
			select {
			case c.out <- msg:
			case <-ctx.Done():
				return
			}
		}
	}()
	return c
}

// streamExpired reports whether a stream must close at now: its
// authenticated subscription's token was revoked (PocketBase cleared the
// client's auth) or has expired, or it never authenticated and is older than
// PocketBase's own lifetime.
func streamExpired(client subscriptions.Client, opened, now time.Time) bool {
	expiry, subscribed := client.Get(tokenExpiryKey).(time.Time)
	if !subscribed {
		return now.Sub(opened) >= realtimeGuestLifetime
	}
	auth, _ := client.Get(apis.RealtimeClientAuthKey).(*core.Record)
	return auth == nil || !now.Before(expiry)
}
