package repoctl

import (
	"path/filepath"
	"testing"
)

func TestCLIContractFoundation(t *testing.T) {
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateCLIContractFoundation(root); err != nil {
		t.Fatal(err)
	}
}
