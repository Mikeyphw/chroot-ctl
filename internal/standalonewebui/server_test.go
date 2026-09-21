package standalonewebui

import (
	"context"
	"io"
	"net/http"
	"net/http/cookiejar"
	"strings"
	"testing"
	"time"
)

func TestLoopbackBootstrapReplayAndAuth(t *testing.T) {
	s, _ := New(Config{IdleTimeout: time.Minute})
	ctx, c := context.WithCancel(context.Background())
	defer c()
	info, e := s.Start(ctx)
	if e != nil {
		t.Fatal(e)
	}
	if !strings.HasPrefix(info.URL, "http://127.0.0.1:") {
		t.Fatalf("not loopback: %s", info.URL)
	}
	jar, _ := cookiejar.New(nil)
	cl := &http.Client{Jar: jar}
	resp, e := cl.Get(info.BootstrapURL)
	if e != nil {
		t.Fatal(e)
	}
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatal(resp.Status)
	}
	resp, e = cl.Get(info.BootstrapURL)
	if e != nil {
		t.Fatal(e)
	}
	resp.Body.Close()
	if resp.StatusCode != 401 {
		t.Fatalf("replay=%d", resp.StatusCode)
	}
	resp, e = cl.Get(info.URL + "/api/v1/health")
	if e != nil {
		t.Fatal(e)
	}
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatal(resp.Status)
	}
	naked, _ := http.Get(info.URL + "/api/v1/health")
	naked.Body.Close()
	if naked.StatusCode != 401 {
		t.Fatalf("unauth=%d", naked.StatusCode)
	}
}
func TestHostRejected(t *testing.T) {
	s, _ := New(Config{})
	ctx, c := context.WithCancel(context.Background())
	defer c()
	info, _ := s.Start(ctx)
	req, _ := http.NewRequest("GET", info.URL+"/api/v1/health", nil)
	req.Host = "evil.example"
	r, e := http.DefaultClient.Do(req)
	if e != nil {
		t.Fatal(e)
	}
	defer r.Body.Close()
	if r.StatusCode != 403 {
		t.Fatalf("status=%d", r.StatusCode)
	}
}
