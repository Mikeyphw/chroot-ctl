package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTmux05PersistentJobsContract(t *testing.T) {
	root := filepath.Join("..", "..")
	checks := map[string][]string{
		"internal/tmuxruntime/jobs.go":         {"type JobStore struct", "JobRecovered", "JobLost", "maxJobEvidenceBytes", "os.Rename", "func (s *JobStore) Reconcile", "Capture(ctx"},
		"internal/services/sessions.go":        {"NewJobStore", "LinkSession(sess)", "Kill(ctx, sess.ID)"},
		"docs/runtime/TMUX_PERSISTENT_JOBS.md": {"TMUX-05 of 7", "restart", "reboot", "bounded evidence", "cleanup"}}
	for rel, wants := range checks {
		b, e := os.ReadFile(filepath.Join(root, rel))
		if e != nil {
			t.Fatal(e)
		}
		for _, w := range wants {
			if !strings.Contains(string(b), w) {
				t.Errorf("%s missing %q", rel, w)
			}
		}
	}
}
