package services

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCHR23RecentLogTailIsBoundedFilteredAndRedacted(t *testing.T) {
	path := filepath.Join(t.TempDir(), "chrootctl.log")
	content := strings.Join([]string{
		"2026-09-14 INFO startup",
		"2026-09-14 WARNING older-warning",
		"2026-09-14 ERROR password=message-secret",
		"2026-09-14 WARNING newer-warning",
		"2026-09-14 CRITICAL newest-critical",
	}, "\n") + "\n"
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}

	lines, truncated, err := readRecentLogLines(path, 3, logSeverityValue("WARNING"))
	if err != nil {
		t.Fatal(err)
	}
	if !truncated {
		t.Fatal("expected exact truncated=true because an older matching record exists")
	}
	if len(lines) != 3 {
		t.Fatalf("lines=%d want=3: %#v", len(lines), lines)
	}
	joined := strings.Join(lines, "\n")
	if strings.Contains(joined, "message-secret") || !strings.Contains(joined, "password=<redacted>") {
		t.Fatalf("tail did not redact secret: %q", joined)
	}
	if strings.Contains(joined, "older-warning") || strings.Contains(joined, "startup") {
		t.Fatalf("tail was not bounded to newest matching records: %q", joined)
	}
}

func TestCHR23RecentLogReaderRejectsSymlinks(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "target.log")
	link := filepath.Join(dir, "link.log")
	if err := os.WriteFile(target, []byte("INFO safe\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, link); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	if _, _, err := readRecentLogLines(link, 10, 0); err == nil || !strings.Contains(err.Error(), "non-symlink") {
		t.Fatalf("expected symlink rejection, got %v", err)
	}
}

func TestCHR23ServiceLifecycleLogRotatesOversizedFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "service.log")
	payload := make([]byte, maxServiceLogBytes+1)
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := rotateServiceLogIfNeeded(path); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("active oversized log still exists: %v", err)
	}
	if st, err := os.Stat(path + ".1"); err != nil || st.Size() != int64(len(payload)) {
		t.Fatalf("rotated log mismatch: stat=%v err=%v", st, err)
	}
}
