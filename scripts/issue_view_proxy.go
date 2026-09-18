// Counting proxy for measure_issue_view.py. Logs request coordinates, never auth.
package main

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"sync"
	"time"
)

type event struct {
	Path    string  `json:"path"`
	Seconds float64 `json:"seconds"`
}

func main() {
	if len(os.Args) != 3 {
		panic("usage: issue_view_proxy API_URL ADDRESS_FILE")
	}
	target, err := url.Parse(os.Args[1])
	if err != nil || target.Host == "" {
		panic("invalid API URL")
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		panic(err)
	}
	proxy := httputil.NewSingleHostReverseProxy(target)
	direct := proxy.Director
	proxy.Director = func(r *http.Request) { direct(r); r.Host = target.Host }
	var mu sync.Mutex
	var events []*event
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/__stats" {
			mu.Lock()
			defer mu.Unlock()
			json.NewEncoder(w).Encode(events)
			return
		}
		if r.URL.Path == "/__reset" {
			mu.Lock()
			events = nil
			mu.Unlock()
			w.WriteHeader(http.StatusNoContent)
			return
		}
		started, path := time.Now(), r.URL.RequestURI()
		entry := &event{Path: path}
		mu.Lock()
		events = append(events, entry)
		mu.Unlock()
		proxy.ServeHTTP(w, r)
		mu.Lock()
		entry.Seconds = time.Since(started).Seconds()
		mu.Unlock()
	})
	if err := os.WriteFile(os.Args[2], []byte("http://"+listener.Addr().String()), 0600); err != nil {
		panic(err)
	}
	if err := http.Serve(listener, handler); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
