package module

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWebUIWR01TypedLifecycleConvergence(t *testing.T) {
	root := filepath.Join("webroot")
	read := func(name string) string {
		b, err := os.ReadFile(filepath.Join(root, name))
		if err != nil { t.Fatal(err) }
		return string(b)
	}
	bridge := read("chrootctl.js")
	ui := read("index.js")
	html := read("index.html")
	for _, want := range []string{"chroots.lifecycle.preview", "chroots.start", "chroots.restart", "chroots.upgrade", "chroots.remove.execute", "previewLifecycle", "runLifecycle"} {
		if !strings.Contains(bridge, want) { t.Fatalf("typed lifecycle contract missing %q", want) }
	}
	for _, forbidden := range []string{"case 'chrootStart'", "case 'chrootRestart'", "case 'chrootRemove'"} {
		if strings.Contains(bridge, forbidden) { t.Fatalf("legacy lifecycle mutation remains: %s", forbidden) }
	}
	for _, want := range []string{"reviewLifecycle(name,action)", "runLifecycle(name,action,preview", "data-action=\"upgrade\"", "cancelOperation(lifecycleState.operationId)"} {
		if !strings.Contains(ui, want) { t.Fatalf("WebUI lifecycle wiring missing %q", want) }
	}
	for _, want := range []string{"id=\"lifecycle-dialog\"", "id=\"lifecycle-confirm\"", "id=\"lifecycle-cancel\"", "id=\"lifecycle-run\""} {
		if !strings.Contains(html, want) { t.Fatalf("lifecycle review UI missing %q", want) }
	}
}
