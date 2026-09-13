package repoctl

import (
	"path/filepath"
	"runtime"
	"testing"
)

func TestValidateInstallerUpgradeReconstruction(t *testing.T) {
	_, file, _, _ := runtime.Caller(0)
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
	if err := ValidateInstallerUpgradeReconstruction(root); err != nil {
		t.Fatal(err)
	}
}
