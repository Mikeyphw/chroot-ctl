package sqlitecompat

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestDSNPreservesLegacyPragmas(t *testing.T) {
	dsn, err := DSN(filepath.Join(t.TempDir(), "registry with spaces.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	for _, fragment := range []string{"_busy_timeout=5000", "_foreign_keys=on", "_journal_mode=WAL", "_synchronous=FULL", "_txlock=immediate"} {
		if !strings.Contains(dsn, fragment) {
			t.Fatalf("DSN %q missing %q", dsn, fragment)
		}
	}
}
