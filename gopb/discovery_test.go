package gopb

import (
	"reflect"
	"testing"
)

// LLL-652: the API port answers its version whether or not a board is
// advertised. LLL-710: it lists its capabilities too.
func TestAPIDiscoveryAlwaysNamesTheVersion(t *testing.T) {
	caps := []string{"issues.idempotency", "comments.idempotency", "webhooks.activity"}
	cases := []struct {
		boardURL string
		want     map[string]any
	}{
		{"", map[string]any{"service": "lll", "version": "1.2.3", "capabilities": caps}},
		{"https://board.example", map[string]any{"service": "lll", "version": "1.2.3", "capabilities": caps, "web_url": "https://board.example"}},
	}
	for _, c := range cases {
		if got := apiDiscovery("1.2.3", c.boardURL); !reflect.DeepEqual(got, c.want) {
			t.Errorf("apiDiscovery(%q) = %v, want %v", c.boardURL, got, c.want)
		}
	}
}
