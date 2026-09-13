package repoctl

import "testing"

func TestMutationEngineGateA(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateMutationEngineGateA(root); err != nil {
		t.Fatal(err)
	}
}
