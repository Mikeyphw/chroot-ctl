package repoctl

import "testing"

func TestValidateBridgeProtocolV2ConvergenceCHR17(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateBridgeProtocolV2Convergence(root); err != nil {
		t.Fatal(err)
	}
}
