package operations

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestJournalRejectsUnsafeIDsAndReadsLegacyAliases(t *testing.T) {
	j, e := NewJournal(t.TempDir())
	if e != nil {
		t.Fatal(e)
	}
	for _, id := range []string{"../escape", "a/b", "..", "bad.id"} {
		if _, e := j.Load(id); e == nil {
			t.Fatalf("accepted %q", id)
		}
	}
	legacy := map[string]any{"operation_id": "legacy1", "kind": "demo", "state": "running", "process_group_id": 123, "progress_text": "Working"}
	b, _ := json.Marshal(legacy)
	if e = os.WriteFile(filepath.Join(j.RecordsDir, "legacy1.json"), b, 0644); e != nil {
		t.Fatal(e)
	}
	r, e := j.Load("legacy1")
	if e != nil || r.SchemaVersion != 1 || r.ProcessGroupID == nil || *r.ProcessGroupID != 123 {
		t.Fatalf("legacy=%#v err=%v", r, e)
	}
}
func TestManagerRedactsAndPersistsEvents(t *testing.T) {
	m, e := NewManager(t.TempDir(), false)
	if e != nil {
		t.Fatal(e)
	}
	r, e := m.Create(CreateOptions{Kind: "test.redaction", Title: "redaction", Request: map[string]any{"password": "secret"}})
	if e != nil {
		t.Fatal(e)
	}
	done, e := m.Execute(context.Background(), &r, func(p ProgressFunc, c func() bool) (any, error) {
		if e := p(map[string]any{"message": "Bearer token-value", "access_token": "abc", "percent": 50}); e != nil {
			return nil, e
		}
		return map[string]any{"password": "result-secret"}, nil
	}, nil)
	if e != nil || done.State != "succeeded" {
		t.Fatalf("done=%#v err=%v", done, e)
	}
	raw, e := os.ReadFile(filepath.Join(m.Journal.RecordsDir, r.OperationID+".json"))
	if e != nil {
		t.Fatal(e)
	}
	s := string(raw)
	if strings.Contains(s, "secret") || strings.Contains(s, "token-value") || strings.Contains(s, "abc") {
		t.Fatalf("secret persisted: %s", s)
	}
	got, e := m.Get(r.OperationID, 200)
	if e != nil || len(got.ProgressEvents) == 0 {
		t.Fatalf("events=%v err=%v", len(got.ProgressEvents), e)
	}
}
func TestReadsDoNotRecoverAndExplicitReconcileDoes(t *testing.T) {
	m, _ := NewManager(t.TempDir(), false)
	r, _ := m.Create(CreateOptions{Kind: "test.stale", Title: "stale"})
	r.State = "running"
	pid := 999999999
	pg := 999999999
	start := int64(1)
	boot := "dead-boot"
	r.PID = &pid
	r.ProcessGroupID = &pg
	r.ProcessStartTime = &start
	r.ProcessBootID = &boot
	if e := m.Journal.Save(&r); e != nil {
		t.Fatal(e)
	}
	got, _ := m.Get(r.OperationID, 20)
	if got.State != "running" {
		t.Fatalf("read mutated=%s", got.State)
	}
	got, e := m.Reconcile(context.Background(), r.OperationID)
	if e != nil || got.State != "interrupted" {
		t.Fatalf("state=%s err=%v", got.State, e)
	}
}
func TestCancelMarkerDeadIdentityReconcilesCancelled(t *testing.T) {
	m, _ := NewManager(t.TempDir(), false)
	r, _ := m.Create(CreateOptions{Kind: "test.cancel", Title: "cancel"})
	r.State = "running"
	pid := 999999999
	pg := 999999999
	start := int64(1)
	boot := "dead-boot"
	r.PID = &pid
	r.ProcessGroupID = &pg
	r.ProcessStartTime = &start
	r.ProcessBootID = &boot
	_ = m.Journal.Save(&r)
	_ = m.Journal.RequestCancel(r.OperationID)
	ids, e := m.Recover(context.Background())
	if e != nil || len(ids) != 1 {
		t.Fatalf("ids=%v err=%v", ids, e)
	}
	got, _ := m.Get(r.OperationID, 20)
	if got.State != "cancelled" {
		t.Fatalf("state=%s", got.State)
	}
}
func TestTargetLockBlocksSecondOperation(t *testing.T) {
	root := t.TempDir()
	j, _ := NewJournal(root)
	l1 := NewLock(j.LocksDir, "target-demo", "one")
	if e := l1.Acquire(); e != nil {
		t.Fatal(e)
	}
	defer l1.Release()
	l2 := NewLock(j.LocksDir, "target-demo", "two")
	if e := l2.Acquire(); e == nil {
		l2.Release()
		t.Fatal("second lock acquired")
	}
}
func TestEventEmitterFailureCannotRewriteSuccess(t *testing.T) {
	m, _ := NewManager(t.TempDir(), false)
	r, _ := m.Create(CreateOptions{Kind: "test.emit", Title: "emit"})
	done, e := m.Execute(context.Background(), &r, func(p ProgressFunc, c func() bool) (any, error) { return map[string]any{"ok": true}, nil }, func(map[string]any) error { return os.ErrClosed })
	if e != nil || done.State != "succeeded" {
		t.Fatalf("state=%s err=%v", done.State, e)
	}
}
