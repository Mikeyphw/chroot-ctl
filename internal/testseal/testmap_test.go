package testseal

import (
	"os"
	"path/filepath"
	"testing"
)

func repoRoot(t *testing.T) string {
	t.Helper()
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Clean(filepath.Join(cwd, "..", ".."))
	if _, err = os.Stat(filepath.Join(root, "go.mod")); err != nil {
		t.Fatalf("repo root: %v", err)
	}
	return root
}
func TestLegacyPythonSuiteMapSurvivesFinalPurge(t *testing.T) {
	if err := Validate(repoRoot(t), false); err != nil {
		t.Fatal(err)
	}
}
