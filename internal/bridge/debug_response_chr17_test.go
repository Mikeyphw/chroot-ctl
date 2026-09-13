package bridge

import (
	"testing"

	"chrootctl/internal/model"
)

func TestCHR17TimelineEventsNormalizeToAndroidShape(t *testing.T) {
	rows := normalizeTimelineEvents([]model.AuditEvent{{EventId: 7, EventType: "support.bundle", Target: "demo", Result: "ok", Message: "done", Actor: "tester", CreatedAt: "now", Metadata: map[string]string{"k": "v"}}})
	if len(rows) != 1 {
		t.Fatalf("rows=%d", len(rows))
	}
	if rows[0]["eventType"] != "support.bundle" || rows[0]["target"] != "demo" || rows[0]["message"] != "done" {
		t.Fatalf("normalized row=%v", rows[0])
	}
}
