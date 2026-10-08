package gopb

import (
	"maps"
	"testing"
)

// LLL-652: the API port answers its version whether or not a board is
// advertised, and names nothing beyond service, version and web_url.
func TestAPIDiscoveryAlwaysNamesTheVersion(t *testing.T) {
	cases := []struct {
		boardURL string
		want     map[string]string
	}{
		{"", map[string]string{"service": "lll", "version": "1.2.3"}},
		{"https://board.example", map[string]string{"service": "lll", "version": "1.2.3", "web_url": "https://board.example"}},
	}
	for _, c := range cases {
		if got := apiDiscovery("1.2.3", c.boardURL); !maps.Equal(got, c.want) {
			t.Errorf("apiDiscovery(%q) = %v, want %v", c.boardURL, got, c.want)
		}
	}
}
