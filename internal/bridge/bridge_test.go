package bridge

import (
	"context"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"chrootctl/internal/operations"
)

func validRequest(op string, p map[string]any) []byte {
	b, _ := json.Marshal(map[string]any{"protocolVersion": 1, "requestId": "req-1", "operation": op, "payload": p})
	return b
}
func TestFrozenCapabilitiesCoverAll90Operations(t *testing.T) {
	if got := len(orderedSpecs); got != 90 {
		t.Fatalf("spec count=%d", got)
	}
	modes := map[string]int{}
	locks := map[string]int{}
	for _, s := range orderedSpecs {
		modes[s.Mode]++
		locks[s.LockScope]++
		if _, e := Resolve(Request{ProtocolVersion: 1, RequestID: "x", Operation: s.Name, Payload: map[string]any{}}, s.Mode); e != nil {
			t.Fatalf("resolve %s: %v", s.Name, e)
		}
	}
	if modes["query"] != 39 || modes["preview"] != 16 || modes["operation"] != 35 {
		t.Fatalf("modes=%v", modes)
	}
	if locks["none"] == 0 || locks["target"] == 0 || locks["global"] == 0 {
		t.Fatalf("locks=%v", locks)
	}
}
func TestProtocolRejectsUnknownAndMalformedInput(t *testing.T) {
	cases := []struct {
		raw  string
		code string
	}{{`[]`, "INVALID_REQUEST"}, {`{"protocolVersion":2,"requestId":"x","operation":"system.dashboard","payload":{}}`, "UNSUPPORTED_PROTOCOL_VERSION"}, {`{"protocolVersion":1,"requestId":"bad id","operation":"system.dashboard","payload":{}}`, "INVALID_REQUEST_ID"}, {`{"protocolVersion":1,"requestId":"x","operation":"Bad","payload":{}}`, "INVALID_OPERATION"}, {`{"protocolVersion":1,"requestId":"x","operation":"system.dashboard","payload":[],"extra":1}`, "UNKNOWN_REQUEST_FIELD"}}
	for _, tc := range cases {
		_, e := ParseRequest([]byte(tc.raw))
		var pe ProtocolError
		if !asProtocolError(e, &pe) || pe.ErrorCode != tc.code {
			t.Fatalf("raw=%s error=%v code=%q want=%q", tc.raw, e, pe.ErrorCode, tc.code)
		}
	}
}
func TestPayloadAllowlistIncludesPreviewContractOnly(t *testing.T) {
	r, e := ParseRequest(validRequest("system.dashboard", map[string]any{"details": true, "previewId": "x", "payloadHash": "y", "resourceRevision": "z"}))
	if e != nil {
		t.Fatal(e)
	}
	if _, e = Resolve(r, "query"); e != nil {
		t.Fatal(e)
	}
	r.Payload["surprise"] = true
	_, e = Resolve(r, "query")
	var pe ProtocolError
	if !asProtocolError(e, &pe) || pe.ErrorCode != "UNKNOWN_PAYLOAD_FIELD" {
		t.Fatalf("%v", e)
	}
}
func TestProtocolShapeLimits(t *testing.T) {
	deep := map[string]any{}
	cur := deep
	for i := 0; i < MaxJSONDepth+2; i++ {
		n := map[string]any{}
		cur["x"] = n
		cur = n
	}
	_, e := ParseRequest(validRequest("system.dashboard", deep))
	var pe ProtocolError
	if !asProtocolError(e, &pe) || pe.ErrorCode != "REQUEST_TOO_DEEP" {
		t.Fatalf("deep=%v", e)
	}
	_, e = ParseRequest(validRequest("system.dashboard", map[string]any{"name": strings.Repeat("x", MaxStringLength+1)}))
	if !asProtocolError(e, &pe) || pe.ErrorCode != "REQUEST_STRING_TOO_LONG" {
		t.Fatalf("string=%v", e)
	}
}
func TestPreviewContractIsOneShotAndBound(t *testing.T) {
	dir := t.TempDir()
	s, e := NewPreviewStore(dir)
	if e != nil {
		t.Fatal(e)
	}
	now := time.Unix(1000, 0)
	s.Now = func() time.Time { return now }
	p := map[string]any{"name": "demo", "action": "start"}
	issued, e := s.Issue("chroots.lifecycle.preview", "chroots.start", p, map[string]any{"ok": true, "name": "demo"})
	if e != nil {
		t.Fatal(e)
	}
	action := map[string]any{"name": "demo", "previewId": issued["previewId"], "payloadHash": issued["payloadHash"], "resourceRevision": issued["resourceRevision"]}
	if _, e = s.Verify("chroots.start", action); e != nil {
		t.Fatal(e)
	}
	if _, e = s.Verify("chroots.start", action); e == nil {
		t.Fatal("preview was reusable")
	}
}
func TestPreviewStoreExpiry(t *testing.T) {
	dir := t.TempDir()
	s, _ := NewPreviewStore(dir)
	now := time.Unix(1000, 0)
	s.Now = func() time.Time { return now }
	p := map[string]any{"name": "demo"}
	issued, e := s.Issue("install.preview", "install.run", p, map[string]any{"ok": true})
	if e != nil {
		t.Fatal(e)
	}
	s.Now = func() time.Time { return now.Add(PreviewTTL + time.Second) }
	action := map[string]any{"name": "demo", "previewId": issued["previewId"], "payloadHash": issued["payloadHash"], "resourceRevision": issued["resourceRevision"]}
	_, e = s.Verify("install.run", action)
	var pe ProtocolError
	if !asProtocolError(e, &pe) || pe.ErrorCode != "PREVIEW_EXPIRED" {
		t.Fatalf("%v", e)
	}
}
func TestCapabilitiesResponseShape(t *testing.T) {
	dir := t.TempDir()
	m, e := operationsForTest(filepath.Join(dir, "operations"))
	if e != nil {
		t.Fatal(e)
	}
	p, _ := NewPreviewStore(filepath.Join(dir, "previews"))
	d := NewDispatcher(fakeBackend{}, m, p)
	c := d.Capabilities()
	if c["protocolVersion"] != 1 || c["arbitraryShell"] != false {
		t.Fatalf("%v", c)
	}
	if len(c["operations"].([]map[string]any)) != 90 {
		t.Fatal("capability count")
	}
}

type fakeBackend struct{}

func (fakeBackend) State(context.Context) (any, error) { return map[string]any{"ok": true}, nil }
func (fakeBackend) Invoke(context.Context, string, string, map[string]any, Progress, func() bool) (any, error) {
	return map[string]any{"ok": true}, nil
}

// wrappers keep this test file focused without exporting test-only constructors.
func operationsForTest(root string) (*operations.Manager, error) {
	return operations.NewManager(root, false)
}

func TestRunAppRejectsMalformedRequestBeforeConfigServices(t *testing.T) {
	var out strings.Builder
	code := RunApp(context.Background(), []string{"--config", "/definitely/missing/config.yaml", "query", "--request-file", "-"}, strings.NewReader(`{"protocolVersion":2,"requestId":"early","operation":"system.dashboard","payload":{}}`), &out, &out)
	if code != 2 {
		t.Fatalf("code=%d out=%s", code, out.String())
	}
	if !strings.Contains(out.String(), `"code":"UNSUPPORTED_PROTOCOL_VERSION"`) {
		t.Fatalf("out=%s", out.String())
	}
	if strings.Contains(out.String(), "no such file") {
		t.Fatalf("config was touched before protocol rejection: %s", out.String())
	}
}
