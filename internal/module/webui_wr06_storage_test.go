package module

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWebUIWR06StorageParity(t *testing.T) {
	read := func(n string) string {
		b, e := os.ReadFile(filepath.Join("webroot", n))
		if e != nil {
			t.Fatal(e)
		}
		return string(b)
	}
	b, j, h := read("chrootctl.js"), read("index.js"), read("index.html")
	for _, x := range []string{"storage.status", "artifacts.list", "transfer.artifact_root", "artifacts.cleanup_preview", "artifacts.cleanup", "previewArtifactCleanup", "runArtifactCleanup"} {
		if !strings.Contains(b, x) {
			t.Fatalf("missing storage/artifact contract %q", x)
		}
	}
	for _, x := range []string{"loadStorage", "renderArtifacts", "executeCleanup", "mismatchedMountCount", "cancelOperation(storageState.operationId)"} {
		if !strings.Contains(j, x) {
			t.Fatalf("missing storage UI wiring %q", x)
		}
	}
	for _, x := range []string{`id="storage-panel"`, `data-route="storage"`, `id="cleanup-dialog"`, `id="artifact-root"`} {
		if !strings.Contains(h, x) {
			t.Fatalf("missing storage surface %q", x)
		}
	}
}
