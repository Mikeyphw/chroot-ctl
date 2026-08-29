package repoctl

import (
	"path/filepath"
	"testing"

	"chrootctl/internal/contracts"
)

func TestLiveContractsMatchFrozenFixtures(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	bundle, err := contracts.LoadDir(filepath.Join(root, "migration", "contracts", "v1"))
	if err != nil {
		t.Fatal(err)
	}
	if err = bundle.Validate(); err != nil {
		t.Fatal(err)
	}
	if err = ValidateLiveContracts(root, bundle); err != nil {
		t.Fatal(err)
	}
}
