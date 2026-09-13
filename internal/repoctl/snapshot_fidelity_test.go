package repoctl

import "testing"

func TestValidateSnapshotFidelity(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateSnapshotFidelity(root); err != nil {
		t.Fatal(err)
	}
}
