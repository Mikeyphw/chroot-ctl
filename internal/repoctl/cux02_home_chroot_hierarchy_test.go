package repoctl

import (
	"os"
	"strings"
	"testing"
)

func TestCUX02HomeAndChrootHierarchy(t *testing.T) {
	html, err := os.ReadFile("../module/webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	js, err := os.ReadFile("../module/webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	h, j := string(html), string(js)
	for _, want := range []string{"home-chroot-count", "home-session-count", "home-job-count", "chroot-context", "context-route"} {
		if !strings.Contains(h, want) {
			t.Fatalf("CUX02 HTML missing %q", want)
		}
	}
	for _, want := range []string{"function openChrootManager", "function loadHome", "data-empty-create", "function bindContextualChrootSelect", "This workspace never guesses a global target"} {
		if !strings.Contains(j, want) {
			t.Fatalf("CUX02 JS missing %q", want)
		}
	}
	if strings.Contains(j, "applyDefaultChrootToSelect") {
		t.Fatal("CUX02 must not restore the brittle global select/default-chroot helper")
	}
	for _, old := range []string{`data-route="users">Users</button>`, `data-route="services">Services</button>`, `data-route="snapshots">Snapshots</button>`, `data-route="storage">Storage</button>`} {
		if strings.Contains(h, `class="tool-route" `+old) {
			t.Fatalf("chroot-scoped tool remains in global Tools sheet: %s", old)
		}
	}
}
