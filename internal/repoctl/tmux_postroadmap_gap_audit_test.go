package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTmuxPostRoadmapGapAudit(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	checks := map[string][]string{
		"internal/tmuxruntime/runtime.go":         {`DefaultStateRoot = "/data/adb/chrootctl/runtime/tmux"`},
		"internal/tmuxruntime/session.go":         {"func (m *SessionManager) Input", `"send-keys"`, "8192"},
		"internal/services/sessions.go":           {"SessionID(n, u)", "existing != nil", "JobKilled", "store.Reconcile"},
		"internal/bridge/specs_generated.go":      {`Name: "sessions.input"`},
		"internal/module/webroot/chrootctl.js":    {"inputSession", "sessions.input"},
		"internal/module/webroot/index.html":      {`id="terminal-input"`, `id="terminal-send"`},
		"docs/runtime/TMUX_FULL_ROADMAP_AUDIT.md": {"Audit 1", "Audit 2", "Audit 3", "Audit 4", "real-device evidence"},
	}
	for rel, wants := range checks {
		b, e := os.ReadFile(filepath.Join(root, rel))
		if e != nil {
			t.Fatal(e)
		}
		text := string(b)
		for _, w := range wants {
			if !strings.Contains(text, w) {
				t.Fatalf("%s missing %q", rel, w)
			}
		}
	}
}
