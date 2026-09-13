package repoctl

import "testing"

func TestCHR18ValidateAndroidOperationRoomRecovery(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateAndroidOperationRoomRecovery(root); err != nil {
		t.Fatal(err)
	}
}
