package repoctl

import (
	"os"
	"strings"
	"testing"
)

// Previous test deliberately required mutable /releases/latest. That behavior
// was superseded by the reviewed, immutable API 26 source lock.
func TestBcloneRuntimeUsesReviewedSourceLock(t *testing.T) {
	script, err := os.ReadFile("../../scripts/install-rclone-android-runtime.sh")
	if err != nil {
		t.Fatal(err)
	}
	text := string(script)
	for _, want := range []string{"bclone-android-source.lock", "git -C \"$git_dir\" fetch --depth=1", "BCLONE_COMMIT", "go mod vendor", "-mod=vendor", "rclone-build-receipt.json"} {
		if !strings.Contains(text, want) {
			t.Fatalf("reviewed source builder missing %q", want)
		}
	}
}
