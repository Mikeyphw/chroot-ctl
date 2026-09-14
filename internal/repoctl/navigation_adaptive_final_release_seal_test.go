package repoctl

import "testing"

func TestCHR20ValidateNavigationAdaptiveFinalReleaseSeal(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateNavigationAdaptiveFinalReleaseSeal(root); err != nil {
		t.Fatal(err)
	}
}
