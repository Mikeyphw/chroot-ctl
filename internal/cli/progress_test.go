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

func TestLiveProgressRendersBytesEntriesAndPathForLogs(t *testing.T) {
	var stderr bytes.Buffer
	a := &App{Inv: Invocation{Globals: Globals{JSON: false}}, Stderr: &stderr}
	if err := a.progress(map[string]any{
		"phase": "extract", "percent": 61, "message": "Extracting root filesystem", "live": true,
		"bytes_done": int64(5 * 1024 * 1024 * 1024), "bytes_total": int64(10 * 1024 * 1024 * 1024),
		"entries": int64(33921), "current_path": "usr/lib/aarch64-linux-gnu/example/library.so",
	}); err != nil {
		t.Fatal(err)
	}
	got := stderr.String()
	for _, want := range []string{"[ 61%] Extracting root filesystem", "5.0 GiB / 10.0 GiB", "33,921 entries", "usr/lib/aarch64-linux-gnu/example/library.so"} {
		if !strings.Contains(got, want) {
			t.Fatalf("progress output %q missing %q", got, want)
		}
	}
}

func TestLiveProgressPathIsTruncatedFromTheLeft(t *testing.T) {
	path := "very/long/path/that/keeps/going/through/usr/lib/aarch64-linux-gnu/libsomething.so"
	got := truncateProgressPath(path, 32)
	if len(got) > 34 { // ellipsis is multi-byte UTF-8; visible width remains <= 32.
		t.Fatalf("truncated path too long: %q", got)
	}
	if !strings.HasPrefix(got, "…") || !strings.HasSuffix(got, "libsomething.so") {
		t.Fatalf("unexpected truncation: %q", got)
	}
}

func TestLiveTTYProgressUpdatesOneLineInPlace(t *testing.T) {
	var stderr bytes.Buffer
	tty := true
	a := &App{Inv: Invocation{Globals: Globals{JSON: false}}, Stderr: &stderr, progressTTYOverride: &tty}
	first := map[string]any{"phase": "extract", "percent": 54, "message": "Extracting root filesystem", "live": true, "bytes_done": int64(1024), "bytes_total": int64(4096), "entries": int64(4), "current_path": "usr/bin/a"}
	second := map[string]any{"phase": "extract", "percent": 58, "message": "Extracting root filesystem", "live": true, "bytes_done": int64(2048), "bytes_total": int64(4096), "entries": int64(8), "current_path": "usr/bin/b"}
	if err := a.progress(first); err != nil {
		t.Fatal(err)
	}
	if err := a.progress(second); err != nil {
		t.Fatal(err)
	}
	beforeFinish := stderr.String()
	if strings.Contains(beforeFinish, "\n") {
		t.Fatalf("TTY live progress should stay on one line: %q", beforeFinish)
	}
	if strings.Count(beforeFinish, "\r") != 2 {
		t.Fatalf("TTY updates=%q", beforeFinish)
	}
	a.finishProgressLine()
	if !strings.HasSuffix(stderr.String(), "\n") {
		t.Fatalf("finished progress line missing newline: %q", stderr.String())
	}
}

func TestLiveTTYProgressClearsLineAndFitsTerminalWidth(t *testing.T) {
	var stderr bytes.Buffer
	tty := true
	width := 64
	a := &App{Inv: Invocation{Globals: Globals{JSON: false}}, Stderr: &stderr, progressTTYOverride: &tty, progressWidthOverride: &width}
	detail := map[string]any{
		"phase": "extract", "percent": 74, "message": "Extracting root filesystem", "live": true,
		"bytes_done": int64(212 * 1024 * 1024 * 1024 / 10), "bytes_total": int64(215 * 1024 * 1024 * 1024 / 10),
		"entries": int64(395571), "current_path": "usr/share/code/resources/app/node_modules/@vscode/vsce-sign/bin/vsce-sign",
	}
	if err := a.progress(detail); err != nil {
		t.Fatal(err)
	}
	got := stderr.String()
	if !strings.HasPrefix(got, "\r\x1b[2K") {
		t.Fatalf("TTY update does not clear the full current line first: %q", got)
	}
	visible := strings.TrimPrefix(got, "\r\x1b[2K")
	if len([]rune(visible)) > width {
		t.Fatalf("visible live line width=%d > %d: %q", len([]rune(visible)), width, visible)
	}
	if !strings.Contains(visible, "Extracting") || !strings.Contains(visible, "395,571 entries") {
		t.Fatalf("compact progress lost core detail: %q", visible)
	}
}

func TestFinishTTYProgressTerminatesLineBeforeFollowingError(t *testing.T) {
	var stderr bytes.Buffer
	tty := true
	width := 80
	a := &App{Inv: Invocation{Globals: Globals{JSON: false}}, Stderr: &stderr, progressTTYOverride: &tty, progressWidthOverride: &width}
	if err := a.progress(map[string]any{"phase": "extract", "percent": 50, "message": "Extracting root filesystem", "live": true, "bytes_done": int64(1), "bytes_total": int64(2)}); err != nil {
		t.Fatal(err)
	}
	a.finishProgressLine()
	if !strings.HasSuffix(stderr.String(), "\x1b[K\n") {
		t.Fatalf("progress line was not cleanly terminated: %q", stderr.String())
	}
}
