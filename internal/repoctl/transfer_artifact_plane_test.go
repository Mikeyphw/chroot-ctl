package repoctl

import "testing"

func TestValidateTransferArtifactPlane(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateTransferArtifactPlane(root); err != nil {
		t.Fatal(err)
	}
}
