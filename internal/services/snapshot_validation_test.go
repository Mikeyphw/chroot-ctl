package services

import "testing"

func TestCHR09SafeBaseUsesCanonicalSnapshotValidation(t *testing.T) {
	cases := []string{"../escape", "bad name", "snap\nshot", "-dash-prefix", "snapshot/child"}
	for _, tc := range cases {
		if got, err := safeBase(tc, "snapshot name"); err == nil {
			t.Fatalf("safeBase(%q) = %q, nil; want validation error", tc, got)
		}
	}
	if got, err := safeBase("pre-upgrade_1", "snapshot name"); err != nil || got != "pre-upgrade_1" {
		t.Fatalf("safeBase(valid) = %q, %v", got, err)
	}
}
