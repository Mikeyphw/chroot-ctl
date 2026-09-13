package services

import (
	"testing"
)

func TestCHR03RegisteredPathRemainsAuthoritativeAcrossConfigRootDrift(t *testing.T) {
	got, err := validateRegisteredTargetPath("/new/default/root", "work", "/old/managed/root/work")
	if err != nil {
		t.Fatal(err)
	}
	if got != "/old/managed/root/work" {
		t.Fatalf("resolved path = %q", got)
	}
}

func TestCHR03RegisteredPathRejectsIdentityAndManagementRoots(t *testing.T) {
	tests := []struct{ name, path string }{
		{"work", "/managed/root/other"},
		{"work", "/managed/root"},
		{"work", "/work"},
		{".snapshots", "/managed/.snapshots"},
	}
	for _, tc := range tests {
		if _, err := validateRegisteredTargetPath("/managed/root", tc.name, tc.path); err == nil {
			t.Fatalf("unsafe registered path accepted: name=%q path=%q", tc.name, tc.path)
		}
	}
}
