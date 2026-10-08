package gopb

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

// LLL-676: only listed origins, exactly; "*" and near-origins are refused at
// boot rather than silently widening or voiding the list.
func TestAllowedOrigins(t *testing.T) {
	got, err := allowedOrigins(" https://Tools.example.com, http://localhost:5173 ,")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(got, " ") != "https://tools.example.com http://localhost:5173" {
		t.Fatalf("parsed %q", got)
	}
	if got, err := allowedOrigins(""); err != nil || len(got) != 0 {
		t.Fatalf("empty must mean none: %q %v", got, err)
	}
	for _, bad := range []string{"*", "https://*.example.com", "null", "example.com", "https://x.example/", "https://u@x.example", "ftp://x.example", "https://x.example?q"} {
		if _, err := allowedOrigins(bad); err == nil {
			t.Errorf("%q was accepted", bad)
		}
	}
}

// Exercised through PocketBase's own router on a real route: a replacement
// that reused PocketBase's middleware Id ran only for unmatched requests
// (preflights), which a handler-level test could not see.
func TestBrowserGuardsOnTheRouter(t *testing.T) {
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	defer app.Cleanup()
	r, err := apis.NewRouter(app)
	if err != nil {
		t.Fatal(err)
	}
	r.Bind(apis.CORS(apis.CORSConfig{AllowOrigins: []string{"*"}})) // what apis.Serve binds
	guardBrowsers(r, []string{"https://tools.example.com"}, "127.0.0.1")
	mux, err := r.BuildMux()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		method, host, origin, wantACAO string
		wantCode                       int
	}{
		{http.MethodGet, "127.0.0.1:8090", "https://tools.example.com", "https://tools.example.com", 200},
		{http.MethodGet, "127.0.0.1:8090", "https://TOOLS.example.com", "https://TOOLS.example.com", 200},
		{http.MethodGet, "127.0.0.1:8090", "http://tools.example.com", "", 200},
		{http.MethodGet, "127.0.0.1:8090", "https://evil.example", "", 200},
		{http.MethodGet, "127.0.0.1:8090", "null", "", 200},
		{http.MethodGet, "localhost:8090", "http://127.0.0.1:8100", "", 200},
		{http.MethodOptions, "127.0.0.1:8090", "https://evil.example", "", 204},
		{http.MethodOptions, "127.0.0.1:8090", "https://tools.example.com", "https://tools.example.com", 204},
		{http.MethodGet, "rebind.attacker.example:8090", "", "", 403},
		{http.MethodGet, "rebind.attacker.example:8090", "https://tools.example.com", "", 403},
	} {
		req := httptest.NewRequest(c.method, "http://"+c.host+"/api/health", nil)
		if c.origin != "" {
			req.Header.Set("Origin", c.origin)
		}
		if c.method == http.MethodOptions {
			req.Header.Set("Access-Control-Request-Method", "POST")
		}
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		if rec.Code != c.wantCode || rec.Header().Get("Access-Control-Allow-Origin") != c.wantACAO {
			t.Errorf("%s Host %q Origin %q: %d ACAO %q, want %d %q", c.method, c.host, c.origin,
				rec.Code, rec.Header().Get("Access-Control-Allow-Origin"), c.wantCode, c.wantACAO)
		}
	}
}

func TestLoopbackHostAllowed(t *testing.T) {
	for _, c := range []struct {
		bind, host string
		ok         bool
	}{
		{"127.0.0.1", "127.0.0.1:8090", true},
		{"127.0.0.1", "localhost:8090", true},
		{"127.0.0.1", "LOCALHOST", true},
		{"127.0.0.1", "[::1]:8090", true},
		{"127.0.0.1", "127.9.9.9", true},
		{"127.0.0.1", "rebind.attacker.example:8090", false},
		{"127.0.0.1", "localhost.attacker.example", false},
		{"127.0.0.1", "192.168.1.5:8090", false},
		{"127.0.0.1", "", false},
		{"localhost", "evil.example", false},
		{"::1", "evil.example", false},
		{"0.0.0.0", "lll.example.com", true},
		{"192.168.1.5", "lll.example.com", true},
	} {
		if got := loopbackHostAllowed(c.bind, c.host); got != c.ok {
			t.Errorf("bind %q host %q: %v, want %v", c.bind, c.host, got, c.ok)
		}
	}
	h := LoopbackHostGuard("127.0.0.1", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	req := httptest.NewRequest(http.MethodGet, "http://rebind.attacker.example:8100/api/health", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("rebinding Host answered %d", rec.Code)
	}
}

// The board proxy presents the API's own host, so a loopback API behind a
// LAN board accepts what the board forwards.
func TestAPIProxyPresentsUpstreamHost(t *testing.T) {
	var seen string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { seen = r.Host }))
	defer upstream.Close()
	target, _ := url.Parse(upstream.URL)
	req := httptest.NewRequest(http.MethodGet, "http://192.168.1.5:8100/api/health", nil)
	NewAPIProxy(target).ServeHTTP(httptest.NewRecorder(), req)
	if seen != target.Host {
		t.Fatalf("upstream saw Host %q, want %q", seen, target.Host)
	}
}

func superuser(t *testing.T, app core.App, email, password string) {
	t.Helper()
	if err := upsertSuperuser(app, email, password); err != nil {
		t.Fatal(err)
	}
}

func superuserPasswordIs(t *testing.T, app core.App, email, password string) bool {
	t.Helper()
	coll, err := app.FindCachedCollectionByNameOrId(core.CollectionNameSuperusers)
	if err != nil {
		t.Fatal(err)
	}
	rec, err := app.FindAuthRecordByEmail(coll, email)
	if err != nil {
		t.Fatal(err)
	}
	return rec.ValidatePassword(password)
}

func TestRetireFallbackAdmin(t *testing.T) {
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	defer app.Cleanup()

	// A data directory booted before LLL-676, now booted with a configured
	// pair under another email: the fallback account is locked out.
	superuser(t, app, fallbackAdminEmail, fallbackAdminPassword)
	var out bytes.Buffer
	if err := retireFallbackAdmin(app, "ops@example.com", "chosen-secret", &out); err != nil {
		t.Fatal(err)
	}
	if superuserPasswordIs(t, app, fallbackAdminEmail, fallbackAdminPassword) {
		t.Fatal("the fallback password still works")
	}
	if !strings.Contains(out.String(), "WARNING") {
		t.Fatalf("no warning: %q", out.String())
	}

	// Same email (the generated pair keeps admin@local.dev): left to the
	// upsert that follows, which replaces the password; still warned.
	superuser(t, app, fallbackAdminEmail, fallbackAdminPassword)
	out.Reset()
	if err := retireFallbackAdmin(app, fallbackAdminEmail, "generated", &out); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "WARNING") {
		t.Fatalf("no warning: %q", out.String())
	}

	// A configured pair that IS the fallback is kept, loudly.
	out.Reset()
	if err := retireFallbackAdmin(app, fallbackAdminEmail, fallbackAdminPassword, &out); err != nil {
		t.Fatal(err)
	}
	if !superuserPasswordIs(t, app, fallbackAdminEmail, fallbackAdminPassword) {
		t.Fatal("an explicitly configured fallback pair was rotated")
	}
	if !strings.Contains(out.String(), "well-known fallback") {
		t.Fatalf("no warning: %q", out.String())
	}

	// Nothing to retire: silent.
	superuser(t, app, fallbackAdminEmail, "something-else")
	out.Reset()
	if err := retireFallbackAdmin(app, "ops@example.com", "chosen-secret", &out); err != nil {
		t.Fatal(err)
	}
	if out.Len() != 0 {
		t.Fatalf("warned with nothing to retire: %q", out.String())
	}
}
