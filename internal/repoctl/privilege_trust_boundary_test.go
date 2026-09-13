package repoctl

import "testing"

func TestPrivilegeTrustBoundary(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidatePrivilegeTrustBoundary(root); err != nil {
		t.Fatal(err)
	}
}
