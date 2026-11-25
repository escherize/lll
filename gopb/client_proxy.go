package gopb

import "net/http"

// UseEnvironmentProxy sets t.Proxy to http.ProxyFromEnvironment.
//
// It is set from Go because the proxy function answers (nil, nil) for "no
// proxy", and from lis 0.12.1 a Go function passed as a Lisette value has a
// nil result turned into an "unexpected nil" error. Every unproxied request
// through such a transport then failed (LLL-814).
func UseEnvironmentProxy(t *http.Transport) {
	t.Proxy = http.ProxyFromEnvironment
}
