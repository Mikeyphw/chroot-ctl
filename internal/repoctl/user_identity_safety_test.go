package repoctl

import "testing"

func TestValidateUserIdentitySafety(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateUserIdentitySafety(root); err != nil {
		t.Fatal(err)
	}
}
