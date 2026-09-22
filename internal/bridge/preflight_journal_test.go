package bridge

import (
	"context"
	"path/filepath"
	"testing"

	"chrootctl/internal/operations"
)

type previewDriftBackend struct{}

func (previewDriftBackend) State(context.Context) (any, error) {
	return map[string]any{"ok": true}, nil
}
func (previewDriftBackend) Invoke(_ context.Context, mode, op string, _ map[string]any, _ Progress, _ func() bool) (any, error) {
	if mode == "preview" && op == "install.preview" {
		return map[string]any{"ok": true, "revision": "new"}, nil
	}
	return map[string]any{"ok": true}, nil
}

func TestInstallPreviewPreflightFailureIsDurablyJournaled(t *testing.T) {
	root := t.TempDir()
	manager, err := operations.NewManager(filepath.Join(root, "operations"), false)
	if err != nil {
		t.Fatal(err)
	}
	previews, err := NewPreviewStore(filepath.Join(root, "previews"))
	if err != nil {
		t.Fatal(err)
	}
	d := NewDispatcher(previewDriftBackend{}, manager, previews)

	payload := map[string]any{"name": "demo"}
	contract, err := previews.Issue("install.preview", "install.run", payload, map[string]any{"ok": true, "revision": "old"})
	if err != nil {
		t.Fatal(err)
	}
	for _, k := range []string{"previewId", "payloadHash", "resourceRevision"} {
		payload[k] = contract[k]
	}

	var emitted []map[string]any
	code := d.Run(context.Background(), Request{ProtocolVersion: 1, RequestID: "install-preflight-1", Operation: "install.run", Payload: payload}, func(event map[string]any) error {
		emitted = append(emitted, event)
		return nil
	})
	if code != 2 {
		t.Fatalf("code=%d events=%v", code, emitted)
	}
	rows, err := manager.ListRecent(10, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 {
		t.Fatalf("records=%d want=1", len(rows))
	}
	r := rows[0]
	if r.Kind != "install.run" || r.State != "blocked" {
		t.Fatalf("record=%+v", r)
	}
	if r.ErrorCode == nil || *r.ErrorCode != "PREVIEW_STALE" {
		t.Fatalf("errorCode=%v", r.ErrorCode)
	}
	if got := r.Request["requestId"]; got != "install-preflight-1" {
		t.Fatalf("requestId=%v", got)
	}
	foundBlocked := false
	for _, event := range emitted {
		if event["type"] != "operation_blocked" {
			continue
		}
		payload, _ := event["payload"].(map[string]any)
		if payload["code"] == "PREVIEW_STALE" {
			foundBlocked = true
		}
	}
	if !foundBlocked {
		t.Fatalf("missing PREVIEW_STALE operation_blocked event: %v", emitted)
	}
}
