package cli

import (
	"bytes"
	"strings"
	"testing"
)

func TestHumanProgressRendersReadablePercentLine(t *testing.T) {
	var stderr bytes.Buffer
	a := &App{Inv: Invocation{Globals: Globals{JSON: false}}, Stderr: &stderr}
	if err := a.progress(map[string]any{"phase": "decompress", "percent": 25, "message": "Decompressing archive"}); err != nil {
		t.Fatal(err)
	}
	if got := stderr.String(); got != "[ 25%] Decompressing archive\n" {
		t.Fatalf("progress output = %q", got)
	}
}

func TestJSONProgressStaysOffStderr(t *testing.T) {
	var stderr bytes.Buffer
	a := &App{Inv: Invocation{Globals: Globals{JSON: true}}, Stderr: &stderr}
	if err := a.progress(map[string]any{"percent": 25, "message": "Decompressing archive"}); err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(stderr.String()) != "" {
		t.Fatalf("JSON progress polluted stderr: %q", stderr.String())
	}
}
