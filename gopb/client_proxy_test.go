package gopb

import (
	"net/http"
	"testing"
)

func TestUseEnvironmentProxyAllowsNoProxy(t *testing.T) {
	for _, name := range []string{"HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"} {
		t.Setenv(name, "")
	}
	transport := &http.Transport{}
	UseEnvironmentProxy(transport)
	req, err := http.NewRequest("GET", "http://127.0.0.1:8090/api/realtime", nil)
	if err != nil {
		t.Fatal(err)
	}
	proxy, err := transport.Proxy(req)
	if err != nil || proxy != nil {
		t.Fatalf("unproxied request: proxy %v, error %v; want nil, nil", proxy, err)
	}
}
