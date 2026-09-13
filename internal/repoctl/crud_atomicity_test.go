package repoctl

import "testing"

func TestValidateCRUDAtomicity(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateCRUDAtomicity(root); err != nil {
		t.Fatal(err)
	}
}
