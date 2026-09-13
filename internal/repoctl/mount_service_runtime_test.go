package repoctl

import "testing"

func TestValidateMountServiceRuntime(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateMountServiceRuntime(root); err != nil {
		t.Fatal(err)
	}
}
