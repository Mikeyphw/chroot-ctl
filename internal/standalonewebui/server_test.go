package standalonewebui

import (
	"context"
	"io"
	"net/http"
	"net/http/cookiejar"
	"os"
	"path/filepath"
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

func TestBootstrapLandingCommitsStrictCookiesBeforeStaticUI(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "index.html"), []byte("standalone-ok"), 0600); err != nil {
		t.Fatal(err)
	}
	s, err := New(Config{IdleTimeout: time.Minute, StaticDir: dir})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	info, err := s.Start(ctx)
	if err != nil {
		t.Fatal(err)
	}
	jar, _ := cookiejar.New(nil)
	cl := &http.Client{Jar: jar, CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}}
	resp, err := cl.Get(info.BootstrapURL)
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK || !strings.Contains(string(body), `http-equiv="refresh"`) || !strings.Contains(string(body), `href="/"`) {
		t.Fatalf("bootstrap status=%d body=%q", resp.StatusCode, body)
	}
	if resp.Header.Get("Location") != "" {
		t.Fatalf("bootstrap must not redirect in external navigation chain: %q", resp.Header.Get("Location"))
	}
	resp2, err := cl.Get(info.URL + "/")
	if err != nil {
		t.Fatal(err)
	}
	defer resp2.Body.Close()
	body2, _ := io.ReadAll(resp2.Body)
	if resp2.StatusCode != http.StatusOK || !strings.Contains(string(body2), "standalone-ok") {
		t.Fatalf("authenticated static status=%d body=%q", resp2.StatusCode, body2)
	}
	resp3, _ := http.Get(info.URL + "/")
	defer resp3.Body.Close()
	if resp3.StatusCode != http.StatusUnauthorized {
		t.Fatalf("unauth static=%d", resp3.StatusCode)
	}
}
