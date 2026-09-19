package services

import (
	"context"
	"testing"
	"time"

	"chrootctl/internal/fsmeta"
)

func TestExtractionProgressReporterEmitsStructuredLiveProgress(t *testing.T) {
	var events []map[string]any
	control := TransferControl{Progress: func(v any) error {
		m, ok := v.(map[string]any)
		if !ok {
			t.Fatalf("event type %T", v)
		}
		events = append(events, m)
		return nil
	}}
	r := newExtractionProgressReporter(context.Background(), control, 1000, 30, 75)
	now := time.Unix(100, 0)
	r.now = func() time.Time { return now }
	r.lastEmit = now.Add(-extractProgressMinInterval)

	if err := r.report(fsmeta.ExtractProgress{BytesRead: 100, Entries: 7, CurrentPath: "usr/bin/tool"}); err != nil {
		t.Fatal(err)
	}
	if len(events) != 1 {
		t.Fatalf("events=%d, want 1", len(events))
	}
	if events[0]["live"] != true || events[0]["bytes_done"] != int64(100) || events[0]["bytes_total"] != int64(1000) || events[0]["entries"] != int64(7) || events[0]["current_path"] != "usr/bin/tool" {
		t.Fatalf("unexpected event: %#v", events[0])
	}
	if events[0]["percent"] != 34 {
		t.Fatalf("percent=%v, want 34", events[0]["percent"])
	}

	now = now.Add(100 * time.Millisecond)
	if err := r.report(fsmeta.ExtractProgress{BytesRead: 200, Entries: 8, CurrentPath: "usr/lib/a"}); err != nil {
		t.Fatal(err)
	}
	if len(events) != 1 {
		t.Fatalf("throttle emitted early: %d", len(events))
	}

	now = now.Add(200 * time.Millisecond)
	if err := r.report(fsmeta.ExtractProgress{BytesRead: 200, Entries: 8, CurrentPath: "usr/lib/a"}); err != nil {
		t.Fatal(err)
	}
	if len(events) != 2 {
		t.Fatalf("events=%d, want 2", len(events))
	}
	if events[1]["percent"] != 39 {
		t.Fatalf("percent=%v, want 39", events[1]["percent"])
	}
}

func TestExtractionProgressReporterFinishEmitsCompleteStructuredDetail(t *testing.T) {
	var events []map[string]any
	control := TransferControl{Progress: func(v any) error {
		m, ok := v.(map[string]any)
		if !ok {
			t.Fatalf("event type %T", v)
		}
		events = append(events, m)
		return nil
	}}
	r := newExtractionProgressReporter(context.Background(), control, 4096, 30, 75)
	now := time.Unix(200, 0)
	r.now = func() time.Time { return now }
	r.lastEmit = now.Add(-extractProgressMinInterval)

	if err := r.report(fsmeta.ExtractProgress{BytesRead: 2048, Entries: 12, CurrentPath: "usr/lib/example.so"}); err != nil {
		t.Fatal(err)
	}
	if err := r.finish(); err != nil {
		t.Fatal(err)
	}
	if len(events) != 2 {
		t.Fatalf("events=%d, want 2", len(events))
	}
	final := events[1]
	if final["phase"] != "extract" || final["percent"] != 75 || final["message"] != "Root filesystem extracted" || final["live"] != true {
		t.Fatalf("unexpected final event: %#v", final)
	}
	if final["bytes_done"] != int64(4096) || final["bytes_total"] != int64(4096) || final["entries"] != int64(12) || final["current_path"] != "usr/lib/example.so" {
		t.Fatalf("final detail incomplete: %#v", final)
	}
}
