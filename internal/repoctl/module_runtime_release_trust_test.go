package repoctl

import "testing"

func TestValidateModuleRuntimeReleaseTrustCHR15(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateModuleRuntimeReleaseTrust(root); err != nil {
		t.Fatal(err)
	}
}
