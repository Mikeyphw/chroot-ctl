package repoctl

import (
	"os"
	"path/filepath"
	"testing"
)

func TestValidateClipboardPrivilegedIntegration(t *testing.T) {
	root, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	root = filepath.Dir(filepath.Dir(root))
	if err := ValidateClipboardPrivilegedIntegration(root); err != nil {
		t.Fatal(err)
	}
}
