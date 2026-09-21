package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTmux03SessionManagerContract(t *testing.T) {
	root := filepath.Join("..", "..")
	checks := map[string][]string{
		"internal/tmuxruntime/session.go":      {"type SessionManager struct", "func (m *SessionManager) List", "func (m *SessionManager) Get", "func (m *SessionManager) Create", "func (m *SessionManager) Detach", "func (m *SessionManager) Kill", "func (m *SessionManager) Capture", "func (m *SessionManager) Resize", "func (m *SessionManager) Reconcile", "exec.CommandContext", "context.WithTimeout", "ManagedSessionPrefix", "@chrootctl_target", "@chrootctl_user"},
		"internal/services/sessions.go":        {"ResolveTarget(ctx, n, true)", "RuntimeFor(n, u)", "LoginInvocation(false, false, u)", "tmuxruntime.CreateRequest"},
		"docs/runtime/TMUX_SESSION_MANAGER.md": {"TMUX-03 of 7", "argv-safe", "bounded", "reconcile"},
	}
	for rel, wants := range checks {
		raw, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			t.Fatalf("read %s: %v", rel, err)
		}
		text := string(raw)
		for _, want := range wants {
			if !strings.Contains(text, want) {
				t.Errorf("%s missing %q", rel, want)
			}
		}
	}
}
