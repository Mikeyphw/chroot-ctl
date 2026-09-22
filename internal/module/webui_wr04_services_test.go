package module

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWebUIWR04ServicesParity(t *testing.T) {
	read := func(n string) string {
		b, e := os.ReadFile(filepath.Join("webroot", n))
		if e != nil {
			t.Fatal(e)
		}
		return string(b)
	}
	b, j, h := read("chrootctl.js"), read("index.js"), read("index.html")
	for _, x := range []string{"services.list", "services.journal", "services.preview", "services.start", "services.stop", "services.restart", "services.enable", "services.disable", "previewServiceMutation", "runServiceMutation"} {
		if !strings.Contains(b, x) {
			t.Fatalf("missing service bridge contract %q", x)
		}
	}
	for _, x := range []string{"loadServicesWorkspace", "reviewServiceAction", "executeServiceAction", "cancelOperation", "refreshServiceJournal"} {
		if !strings.Contains(j, x) {
			t.Fatalf("missing service UI wiring %q", x)
		}
	}
	for _, x := range []string{`id="services-panel"`, `data-route="services"`, `id="service-action-dialog"`, `id="service-action-cancel"`} {
		if !strings.Contains(h, x) {
			t.Fatalf("missing services surface %q", x)
		}
	}
}
