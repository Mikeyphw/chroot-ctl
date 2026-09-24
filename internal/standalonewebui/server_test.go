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
	resp3, err := http.Get(info.URL + "/")
	if err != nil {
		t.Fatal(err)
	}
	defer resp3.Body.Close()
	if resp3.StatusCode != http.StatusUnauthorized {
		t.Fatalf("unauth static=%d", resp3.StatusCode)
	}
}

func TestAuthenticatedActivityRefreshesSession(t *testing.T) {
	s, err := New(Config{IdleTimeout: time.Minute, SessionTTL: time.Minute})
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
	cl := &http.Client{Jar: jar}
	resp, err := cl.Get(info.BootstrapURL)
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("bootstrap=%d", resp.StatusCode)
	}

	// Force the authenticated session inside the renewal window without relying
	// on wall-clock sleeps, then prove the next valid request extends it.
	var sid string
	s.mu.Lock()
	for id, sess := range s.sessions {
		sid = id
		sess.expires = time.Now().Add(10 * time.Second)
		s.sessions[id] = sess
		break
	}
	s.mu.Unlock()
	if sid == "" {
		t.Fatal("bootstrap session missing")
	}
	resp, err = cl.Get(info.URL + "/api/v1/health")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("refresh health=%d", resp.StatusCode)
	}
	if got := len(resp.Header.Values("Set-Cookie")); got < 2 {
		t.Fatalf("session refresh Set-Cookie count=%d want>=2", got)
	}
	s.mu.Lock()
	renewed := s.sessions[sid].expires
	s.mu.Unlock()
	if time.Until(renewed) < 45*time.Second {
		t.Fatalf("session was not renewed far enough: expires in %s", time.Until(renewed))
	}
}

func TestRejectedMutationDoesNotRefreshSession(t *testing.T) {
	s, err := New(Config{IdleTimeout: time.Minute, SessionTTL: time.Minute, Dispatcher: &fakeDispatcher{}})
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
	cl := &http.Client{Jar: jar}
	resp, err := cl.Get(info.BootstrapURL)
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()

	var sid string
	shortExpiry := time.Now().Add(10 * time.Second)
	s.mu.Lock()
	for id, sess := range s.sessions {
		sid = id
		sess.expires = shortExpiry
		s.sessions[id] = sess
		break
	}
	s.mu.Unlock()
	if sid == "" {
		t.Fatal("bootstrap session missing")
	}

	req, _ := http.NewRequest(http.MethodPost, info.URL+"/api/v1/query/chroots.list", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-CSRF-Token", "wrong-token")
	req.Header.Set("Origin", info.URL)
	resp, err = cl.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("invalid csrf status=%d", resp.StatusCode)
	}
	if got := len(resp.Header.Values("Set-Cookie")); got != 0 {
		t.Fatalf("rejected mutation refreshed cookies count=%d", got)
	}
	s.mu.Lock()
	after := s.sessions[sid].expires
	s.mu.Unlock()
	if after.After(shortExpiry.Add(time.Second)) {
		t.Fatalf("rejected mutation extended server session: before=%s after=%s", shortExpiry, after)
	}
}
