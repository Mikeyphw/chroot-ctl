package repoctl

import "testing"

func TestBuildFoundationContract(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateBuildFoundation(root); err != nil {
		t.Fatal(err)
	}
}
