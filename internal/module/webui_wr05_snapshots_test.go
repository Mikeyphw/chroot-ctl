package module

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWebUIWR05SnapshotsParity(t *testing.T) {
	read := func(n string) string {
		b, e := os.ReadFile(filepath.Join("webroot", n))
		if e != nil {
			t.Fatal(e)
		}
		return string(b)
	}
	b, j, h := read("chrootctl.js"), read("index.js"), read("index.html")
	for _, x := range []string{"snapshots.list", "snapshots.preview", "snapshots.create", "snapshots.restore", "snapshots.export", "previewSnapshot", "runSnapshot"} {
		if !strings.Contains(b, x) {
			t.Fatalf("missing snapshot bridge contract %q", x)
		}
	}
	for _, x := range []string{"loadSnapshots", "reviewSnapshot", "executeSnapshot", "confirmation", "cancelOperation(snapshotsState.operationId)"} {
		if !strings.Contains(j, x) {
			t.Fatalf("missing snapshot UI wiring %q", x)
		}
	}
	for _, x := range []string{`id="snapshots-panel"`, `data-route="snapshots"`, `id="snapshot-dialog"`, `id="snapshot-confirm"`, `id="snapshot-archive"`} {
		if !strings.Contains(h, x) {
			t.Fatalf("missing snapshots surface %q", x)
		}
	}
}
