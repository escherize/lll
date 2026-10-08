package gopb

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"slices"
	"time"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/core"
)

// Outbound webhooks (LLL-409): registered URLs that receive issue events.
// The realtime fan-out that drives the board's SSE already sees every issue
// create/update/delete server-side; these hooks POST the same events out to
// whoever registered for them, so CI jobs, relays and supervisors can react
// without holding a process and a token open.
//
// Deliveries fire on the After*Success hooks, i.e. after the change is
// committed, and each POST runs on its own goroutine so a slow or dead
// receiver never delays the board write that caused it. A delivery that
// fails — transport error or non-2xx answer — is retried with exponential
// backoff, three attempts in total (LLL-416). The cap is deliberate: a dead
// receiver holds one event for two retries and cannot queue work without
// limit. Every failed attempt is printed to the server's stderr with a
// "webhook:" prefix, the last one final — a delivery that silently dropped
// would be worse than none.
//
// No SSRF guard: a webhook is registered by an authenticated member of this
// server, who can already query every issue through it, and guarding private
// ranges would also forbid the legitimate local receiver (a relay or agent
// supervisor on the same box).
//
// The SSE path is untouched: these hooks add outbound POSTs and read nothing
// from the realtime service.

// Delivery header carrying the registration's secret, so a receiver can
// authenticate that a POST came from this lll and not from anyone who found
// the URL. No member token ever rides a delivery — that is the "no new auth
// surface" constraint the issue set.
const webhookSecretHeader = "X-LLL-Secret"

// One attempt's timeout: long enough for a slow relay, short enough that a
// wedged receiver cannot pile up retrying goroutines on a busy board.
var webhookHTTPClient = &http.Client{Timeout: 10 * time.Second}

// The retry schedule behind that cap (LLL-416): attempt one fires
// immediately, a failure waits delays[0] (1s) before attempt two and
// delays[1] (4s) before attempt three. The ×4 exponential step would next
// wait 16s before a fourth attempt; the cap ends the schedule there, and
// with it a delivery's retries at ~5s of backoff in the worst case.
var webhookRetryDelays = [...]time.Duration{time.Second, 4 * time.Second}

func registerWebhookDelivery(app core.App) {
	deliver := func(action string, e *core.RecordEvent) error {
		webhookDeliver(app, action, e.Record)
		return e.Next()
	}
	app.OnRecordAfterCreateSuccess("issues").BindFunc(func(e *core.RecordEvent) error {
		return deliver("create", e)
	})
	app.OnRecordAfterUpdateSuccess("issues").BindFunc(func(e *core.RecordEvent) error {
		return deliver("update", e)
	})
	app.OnRecordAfterDeleteSuccess("issues").BindFunc(func(e *core.RecordEvent) error {
		return deliver("delete", e)
	})
}

// registerWebhookRecords keeps a webhook's secret write-only and stamps its
// creator (LLL-661, 1792200000_webhook_secret_creator.js).
//
//   - Create: PocketBase drops a hidden field from a member's request body,
//     so the secret is read from the body here. The creator is the calling
//     member; a body value is ignored. A superuser is not a member and
//     leaves the body's creator, usually none.
//   - Every save derives secret_set, the only thing a reader learns about
//     the secret.
//   - Enrich hides the secret from every response, a superuser's included.
//     It runs after e.Next(), because PocketBase unhides every field for a
//     superuser at the end of the enrich chain.
func registerWebhookRecords(app core.App) {
	app.OnRecordCreateRequest("webhooks").BindFunc(func(e *core.RecordRequestEvent) error {
		var body struct {
			Secret string `json:"secret" form:"secret"`
		}
		if err := e.BindBody(&body); err != nil {
			return e.BadRequestError("Failed to read the submitted data.", err)
		}
		e.Record.Set("secret", body.Secret)
		if e.Auth != nil && e.Auth.Collection().Name == "members" {
			e.Record.Set("creator", e.Auth.Id)
		}
		return e.Next()
	})
	secretSet := func(e *core.RecordEvent) error {
		e.Record.Set("secret_set", e.Record.GetString("secret") != "")
		return e.Next()
	}
	app.OnRecordCreate("webhooks").BindFunc(secretSet)
	app.OnRecordUpdate("webhooks").BindFunc(secretSet)
	app.OnRecordEnrich("webhooks").BindFunc(func(e *core.RecordEnrichEvent) error {
		record := e.Record
		err := e.Next()
		record.Hide("secret")
		return err
	})
}

// webhookCreatorReads reports whether a registration may still receive its
// team's events (LLL-661): its creator still reads the team, by the access
// the collection rules compute. A registration with no creator predates the
// field or was made by a superuser; it delivers while its team exists.
func webhookCreatorReads(app core.App, hook *core.Record) bool {
	team := hook.GetString("team")
	creatorID := hook.GetString("creator")
	if creatorID == "" {
		_, err := app.FindRecordById("teams", team)
		return err == nil
	}
	creator, err := app.FindRecordById("members", creatorID)
	return err == nil && effectiveAccess(app, creator).sees(team)
}

// webhookDeliver finds every registration matching the issue's scope and
// hands each one the event. Scope: a registration's team must be the issue's
// team; a project on the registration narrows it to that project's issues.
// A registration whose creator lost read access to the team is skipped and
// logged.
func webhookDeliver(app core.App, action string, issue *core.Record) {
	hooks, err := app.FindRecordsByFilter(
		"webhooks",
		"team = {:team} && (project = '' || project = null || project = {:project})",
		"-created", 500, 0,
		dbx.Params{
			"team":    issue.GetString("team"),
			"project": issue.GetString("project"),
		},
	)
	if err != nil {
		log.Printf("webhook: matching registrations for delivery failed: %v", err)
		return
	}
	if len(hooks) == 0 {
		return
	}
	payload, err := webhookPayload(app, action, issue)
	if err != nil {
		log.Printf("webhook: encoding %s payload failed: %v", action, err)
		return
	}
	for _, hook := range hooks {
		if !webhookCreatorReads(app, hook) {
			log.Printf("webhook: skipped delivery to %s: its creator no longer reads team %s", hook.GetString("url"), hook.GetString("team"))
			continue
		}
		go webhookPostWithRetries(hook.GetString("url"), hook.GetString("secret"), payload, webhookRetryDelays[:])
	}
}

// webhookPayload renders the event the same way `lll watch --json` prints
// one: an envelope of topic, action and record, with the record's team and
// assignee expanded so a receiver can print an issue key (ENG-12) without a
// second request. The expand is set on a clone, never on the record the
// request is still using.
func webhookPayload(app core.App, action string, issue *core.Record) ([]byte, error) {
	clone := issue.Clone()
	expand := map[string]any{}
	if id := clone.GetString("team"); id != "" {
		if team, err := app.FindRecordById("teams", id); err == nil {
			expand["team"] = team
		}
	}
	// Any read-write member of the team may register a webhook, a scoped
	// guest included, and the payload carries no viewer. So the assignee is
	// expanded only when every member of the team may see it (LLL-551,
	// onTeamRoster), and never with another team's id.
	if id := clone.GetString("assignee"); id != "" {
		if assignee, err := app.FindRecordById("members", id); err == nil && onTeamRoster(assignee, clone.GetString("team")) {
			assignee = assignee.Clone()
			teams := slices.DeleteFunc(slices.Clone(assignee.GetStringSlice("teams")), func(t string) bool { return t != clone.GetString("team") })
			assignee.Set("teams", teams)
			expand["assignee"] = assignee
		}
	}
	clone.SetExpand(expand)
	return json.Marshal(struct {
		Topic  string       `json:"topic"`
		Action string       `json:"action"`
		Record *core.Record `json:"record"`
	}{Topic: "issues", Action: action, Record: clone})
}

// webhookPost is one delivery attempt. Both failure shapes — transport error
// and non-2xx answer — reach the server log by the same line format, and the
// returned error is what the retry loop schedules on.
func webhookPost(url, secret string, payload []byte) error {
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		log.Printf("webhook: delivery to %s failed: %v", url, err)
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if secret != "" {
		req.Header.Set(webhookSecretHeader, secret)
	}
	resp, err := webhookHTTPClient.Do(req)
	if err != nil {
		log.Printf("webhook: delivery to %s failed: %v", url, err)
		return err
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)
	if resp.StatusCode >= 300 {
		log.Printf("webhook: delivery to %s answered %s", url, resp.Status)
		return fmt.Errorf("receiver answered %s", resp.Status)
	}
	return nil
}

// webhookPostWithRetries delivers one event to one registration: attempt
// once, then wait delays[i] before each retry, until an attempt succeeds or
// the schedule runs out. It runs entirely on the goroutine webhookDeliver
// spawned, so retries never touch the request path. A first-try success
// logs nothing, exactly like the one-shot delivery this replaces; a success
// after failures logs one line so the recovery is visible beside the
// failure lines that preceded it.
func webhookPostWithRetries(url, secret string, payload []byte, delays []time.Duration) {
	for attempt := 0; ; attempt++ {
		err := webhookPost(url, secret, payload)
		if err == nil {
			if attempt > 0 {
				s := "s"
				if attempt == 1 {
					s = ""
				}
				log.Printf("webhook: delivered to %s after %d failed attempt%s", url, attempt, s)
			}
			return
		}
		if attempt >= len(delays) {
			return // final failure: webhookPost logged it above
		}
		time.Sleep(delays[attempt])
	}
}
