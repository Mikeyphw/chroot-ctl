package repoctl

import "testing"

func TestCHR19ValidateAndroidProductWorkspaceCorrectness(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateAndroidProductWorkspaceCorrectness(root); err != nil {
		t.Fatal(err)
	}
}
