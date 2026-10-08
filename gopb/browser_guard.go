package gopb

import (
	"crypto/rand"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"slices"
	"strings"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/hook"
	"github.com/pocketbase/pocketbase/tools/router"
)

// LLL-676. Three browser-facing defences for the API:
//
//   - CORS names only the origins the operator lists in LLL_ALLOWED_ORIGINS.
//     PocketBase's default is "*", which let any web page the user visited
//     log in to a loopback board and read the token.
//   - A listener bound to loopback answers only loopback Host names, so a
//     DNS-rebinding page (same origin as far as the browser knows) is refused.
//   - The well-known fallback administrator password is retired at boot.

// fallbackAdminEmail and fallbackAdminPassword are the pair 'lll up' used
// before LLL-676 when LLL_ADMIN_* was unset. Existing data directories may
// still hold a superuser with them; retireFallbackAdmin finds it.
const (
	fallbackAdminEmail    = "admin@local.dev"
	fallbackAdminPassword = "admin-local-123"
)

const loopbackHostMessage = "this lll server listens on loopback and answers only loopback host names (localhost, 127.0.0.1, [::1]); the request named another host"

// allowedOrigins parses LLL_ALLOWED_ORIGINS: a comma-separated list of exact
// browser origins (scheme://host[:port]). Empty means no cross-origin browser
// access at all. "*" and anything with a path, query or credentials are
// refused, so a typo cannot silently widen or void the list.
func allowedOrigins(raw string) ([]string, error) {
	var out []string
	for _, part := range strings.Split(raw, ",") {
		origin := strings.TrimSpace(part)
		if origin == "" {
			continue
		}
		u, err := url.Parse(origin)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" ||
			u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" ||
			strings.Contains(origin, "*") {
			return nil, fmt.Errorf("LLL_ALLOWED_ORIGINS: %q is not an origin; list exact origins such as https://tools.example.com or http://localhost:5173, separated by commas", origin)
		}
		out = append(out, strings.ToLower(origin))
	}
	return out, nil
}

// corsMiddleware replaces PocketBase's "*" with an exact-match allow list.
// A request from any other origin still runs (CORS is enforced by the
// browser, not the server), but its response carries no
// Access-Control-Allow-Origin, so the page cannot read it.
//
// It needs its own Id: Router.Unbind(pbCors) also excludes that Id on every
// registered route, so a replacement reusing it would run only for requests
// no route matches (preflights), not for the requests that matter.
func corsMiddleware(origins []string) *hook.Handler[*core.RequestEvent] {
	h := apis.CORS(apis.CORSConfig{
		AllowOriginFunc: func(origin string) (bool, error) {
			return slices.Contains(origins, strings.ToLower(origin)), nil
		},
		AllowMethods: []string{http.MethodGet, http.MethodHead, http.MethodPut, http.MethodPatch, http.MethodPost, http.MethodDelete},
	})
	h.Id = "lllCors"
	return h
}

// isLoopbackName reports whether host (no port) is "localhost" or a
// loopback IP literal.
func isLoopbackName(host string) bool {
	host = strings.TrimSuffix(strings.TrimPrefix(host, "["), "]")
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// hostName strips the port from a Host header value.
func hostName(hostport string) string {
	if h, _, err := net.SplitHostPort(hostport); err == nil {
		return h
	}
	return hostport
}

// loopbackHostAllowed is the DNS-rebinding check: on a loopback listener the
// request's Host must be a loopback name. A rebinding page's Host is the
// attacker's DNS name.
func loopbackHostAllowed(bind, requestHost string) bool {
	return !isLoopbackName(bind) || isLoopbackName(hostName(requestHost))
}

// LoopbackHostGuard wraps the board's handler with the same check the API
// listener applies. bind is the listen address without a port.
func LoopbackHostGuard(bind string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !loopbackHostAllowed(bind, r.Host) {
			http.Error(w, loopbackHostMessage, http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// NewAPIProxy is the board's /api/ reverse proxy. It presents the API's own
// host upstream: the board has already applied its own Host check, and a
// loopback API behind a LAN board must accept what the board forwards.
func NewAPIProxy(target *url.URL) *httputil.ReverseProxy {
	proxy := httputil.NewSingleHostReverseProxy(target)
	direct := proxy.Director
	proxy.Director = func(r *http.Request) {
		direct(r)
		r.Host = target.Host
	}
	return proxy
}

// guardBrowsers swaps PocketBase's "*" CORS for the allow list and adds the
// loopback Host check. Called from OnServe, after PocketBase bound its own.
func guardBrowsers(r *router.Router[*core.RequestEvent], origins []string, bindHost string) {
	r.Unbind(apis.DefaultCorsMiddlewareId)
	r.Bind(corsMiddleware(origins))
	r.Bind(loopbackHostMiddleware(bindHost))
}

func loopbackHostMiddleware(bind string) *hook.Handler[*core.RequestEvent] {
	return &hook.Handler[*core.RequestEvent]{
		Id:       "lllLoopbackHost",
		Priority: apis.DefaultCorsMiddlewarePriority - 1,
		Func: func(e *core.RequestEvent) error {
			if !loopbackHostAllowed(bind, e.Request.Host) {
				return e.ForbiddenError(loopbackHostMessage, nil)
			}
			return e.Next()
		},
	}
}

// retireFallbackAdmin runs before the configured superuser is upserted. A
// superuser still signing in with the well-known fallback password loses it:
// when it is the configured account, the upsert that follows replaces the
// password; otherwise it gets a random password nobody holds, and the
// configured pair is the way in. When the configured password IS the
// fallback (a script exporting it), it is kept and the boot warns.
func retireFallbackAdmin(app core.App, email, password string, w io.Writer) error {
	if password == fallbackAdminPassword {
		fmt.Fprintf(w, "admin  WARNING: LLL_ADMIN_PASSWORD is the well-known fallback 'admin-local-123'; any local process or web page that reaches this server can sign in as %s. Unset LLL_ADMIN_EMAIL and LLL_ADMIN_PASSWORD to get a generated one.\n", email)
		return nil
	}
	superusers, err := app.FindCachedCollectionByNameOrId(core.CollectionNameSuperusers)
	if err != nil {
		return err
	}
	record, err := app.FindAuthRecordByEmail(superusers, fallbackAdminEmail)
	if err != nil || !record.ValidatePassword(fallbackAdminPassword) {
		return nil
	}
	fmt.Fprintf(w, "admin  WARNING: %s had the well-known fallback password 'admin-local-123', which any web page could use; it no longer works. Sign in as %s with this server's administrator password (LLL_ADMIN_PASSWORD, or the generated one the admin line below points to).\n", fallbackAdminEmail, email)
	if strings.EqualFold(email, fallbackAdminEmail) {
		return nil
	}
	record.SetPassword(rand.Text() + rand.Text())
	if err := app.Save(record); err != nil {
		return fmt.Errorf("retiring the well-known fallback administrator password: %w", err)
	}
	return nil
}
