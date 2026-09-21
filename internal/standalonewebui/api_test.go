package standalonewebui

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/cookiejar"
	"testing"
	"time"

	"chrootctl/internal/bridge"
)

type fakeDispatcher struct {
	last bridge.Request
	mode string
}

func (f *fakeDispatcher) Capabilities() map[string]any {
	return map[string]any{"arbitraryShell": false, "operations": bridge.Capabilities()}
}
func (f *fakeDispatcher) State(context.Context, string) bridge.Response {
	return bridge.Success("state", map[string]any{"ok": true})
}
func (f *fakeDispatcher) Query(_ context.Context, r bridge.Request) bridge.Response {
	f.last = r
	f.mode = "query"
	return bridge.Success(r.RequestID, map[string]any{"operation": r.Operation})
}
func (f *fakeDispatcher) Preview(_ context.Context, r bridge.Request) bridge.Response {
	f.last = r
	f.mode = "preview"
	return bridge.Success(r.RequestID, map[string]any{"operation": r.Operation})
}
func (f *fakeDispatcher) Run(_ context.Context, r bridge.Request, emit func(map[string]any) error) int {
	f.last = r
	f.mode = "operation"
	_ = emit(map[string]any{"type": "result", "operation": r.Operation})
	return 0
}
func (f *fakeDispatcher) Operation(id string) bridge.Response {
	return bridge.Success("op", map[string]any{"id": id})
}
func (f *fakeDispatcher) Cancel(id string) bridge.Response {
	return bridge.Success("cancel", map[string]any{"id": id})
}
func (f *fakeDispatcher) Reconcile(_ context.Context, id string) bridge.Response {
	return bridge.Success("reconcile", map[string]any{"id": id})
}

func authedClient(t *testing.T, d Dispatcher) (*http.Client, Info) {
	t.Helper()
	s, err := New(Config{IdleTimeout: time.Minute, Dispatcher: d})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
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
	if resp.StatusCode != 200 {
		t.Fatalf("bootstrap=%d", resp.StatusCode)
	}
	return cl, info
}
func csrf(t *testing.T, cl *http.Client, info Info) string {
	t.Helper()
	req, _ := http.NewRequest("GET", info.URL+"/api/v1/health", nil)
	resp, err := cl.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	u, _ := req.URL.Parse(info.URL)
	for _, c := range cl.Jar.Cookies(u) {
		if c.Name == "chrootctl_csrf" {
			return c.Value
		}
	}
	t.Fatal("csrf cookie missing")
	return ""
}
func post(t *testing.T, cl *http.Client, info Info, path string, body any, token string) *http.Response {
	t.Helper()
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST", info.URL+path, bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-CSRF-Token", token)
	req.Header.Set("Origin", info.URL)
	resp, err := cl.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}
func TestTypedHTTPMapsQueryPreviewAndOperation(t *testing.T) {
	d := &fakeDispatcher{}
	cl, info := authedClient(t, d)
	token := csrf(t, cl, info)
	for _, tc := range []struct{ path, mode, op string }{{"/api/v1/query/sessions.capture", "query", "sessions.capture"}, {"/api/v1/preview/catalog.preview", "preview", "catalog.preview"}, {"/api/v1/run/sessions.input", "operation", "sessions.input"}} {
		resp := post(t, cl, info, tc.path, map[string]any{"id": "s1"}, token)
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		if resp.StatusCode != 200 {
			t.Fatalf("%s=%d", tc.path, resp.StatusCode)
		}
		if d.mode != tc.mode || d.last.Operation != tc.op {
			t.Fatalf("dispatch=%s/%s", d.mode, d.last.Operation)
		}
	}
}
func TestMutationRequiresCSRFAndOrigin(t *testing.T) {
	d := &fakeDispatcher{}
	cl, info := authedClient(t, d)
	resp := post(t, cl, info, "/api/v1/query/chroots.list", map[string]any{}, "")
	resp.Body.Close()
	if resp.StatusCode != 403 {
		t.Fatalf("csrf=%d", resp.StatusCode)
	}
}
func TestNoGenericShellRoute(t *testing.T) {
	d := &fakeDispatcher{}
	cl, info := authedClient(t, d)
	token := csrf(t, cl, info)
	for _, p := range []string{"/api/v1/shell", "/api/v1/exec", "/api/v1/argv", "/api/v1/root-rpc"} {
		resp := post(t, cl, info, p, map[string]any{"command": "id"}, token)
		resp.Body.Close()
		if resp.StatusCode == 200 {
			t.Fatalf("dangerous route accepted: %s", p)
		}
	}
}
