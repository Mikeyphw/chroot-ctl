package services

import "testing"

func TestActiveRuntimeExecutablePathTargetsNativeRuntime(t *testing.T) {
	got := activeRuntimeExecutablePath()
	want := "/data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl"
	if got != want {
		t.Fatalf("activeRuntimeExecutablePath() = %q, want %q", got, want)
	}
}
