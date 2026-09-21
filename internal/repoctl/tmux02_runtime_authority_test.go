package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTMUX02RuntimeAuthorityContract(t *testing.T) {
	root := filepath.Clean(filepath.Join("..", ".."))
	checks := map[string][]string{
		"internal/tmuxruntime/runtime.go":      {"DefaultStateRoot = \"/data/adb/chrootctl/runtime/tmux\"", "DefaultNamespace = \"chrootctl\"", "tmux-runtime-manifest.json", "tmux.sha256", "EM_AARCH64", "ExpectedVersion", "0700", "stale tmux sockets detected"},
		"internal/bridge/specs_generated.go":   {"sessions.runtime", "bundled tmux runtime readiness"},
		"internal/bridge/backend.go":           {"case \"sessions.runtime\"", "tmuxruntime.Inspect(ctx)"},
		"internal/bridge/response_schemas.go":  {"\"sessions.runtime\"", "staleSockets", "namespace"},
		"docs/runtime/TMUX_BACKEND_RUNTIME.md": {"never searches `PATH`", "sole authority", "secret-free health model"},
	}
	for path, wants := range checks {
		b, e := os.ReadFile(filepath.Join(root, path))
		if e != nil {
			t.Fatal(e)
		}
		s := string(b)
		for _, want := range wants {
			if !strings.Contains(s, want) {
				t.Fatalf("%s missing %q", path, want)
			}
		}
	}
	b, _ := os.ReadFile(filepath.Join(root, "internal/tmuxruntime/runtime.go"))
	if strings.Contains(string(b), "exec.LookPath") {
		t.Fatal("production tmux resolver must not use PATH")
	}
}
