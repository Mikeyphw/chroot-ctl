package repoctl

import (
	"path/filepath"
	"runtime"
	"testing"
)

func TestValidateCatalogPackageWorkflow(t *testing.T) {
	_, file, _, _ := runtime.Caller(0)
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
	if err := ValidateCatalogPackageWorkflow(root); err != nil {
		t.Fatal(err)
	}
}
