package repoctl

import "testing"

func TestConfigRegistryFoundation(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateConfigRegistryFoundation(root); err != nil {
		t.Fatal(err)
	}
}
