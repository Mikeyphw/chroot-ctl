package repoctl

import "testing"

func TestProcessTransportBoundary(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateProcessTransportBoundary(root); err != nil {
		t.Fatal(err)
	}
}
