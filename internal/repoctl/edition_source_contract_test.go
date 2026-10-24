package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestEditionsRejectInvalidNamesAndMissingEmbeddedBinary(t *testing.T) {
	for _, name := range []string{"STANDARD", "rclone+debug", "../rclone", "auto", "both"} {
		if err := validateEditionOption(name); err == nil {
			t.Fatalf("accepted invalid edition %q", name)
		}
	}
	for _, name := range []string{"", EditionStandard, EditionRclone} {
		if err := validateEditionOption(name); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := verifyRcloneSource(""); err == nil {
		t.Fatal("missing pinned binary accepted")
	}
	d := t.TempDir()
	p := filepath.Join(d, "rclone")
	if err := os.WriteFile(p, []byte("not a native runtime"), 0755); err != nil {
		t.Fatal(err)
	}
	if _, err := verifyRcloneSource(p); err == nil {
		t.Fatal("invalid embedded binary accepted")
	}
}

func TestApi26PinnedSourceAndNoMutableRelease(t *testing.T) {
	script, err := os.ReadFile("../../scripts/install-rclone-android-runtime.sh")
	if err != nil {
		t.Fatal(err)
	}
	lock, err := os.ReadFile("../../config/chrootctl/bclone-android-source.lock")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"android_api=26", "commit=7b63b1a4cc9d13465721ebbfc96f2f9bd810f600", "ndk_revision=29.0.14206865"} {
		if !strings.Contains(string(lock), want) {
			t.Errorf("missing lock %s", want)
		}
	}
	for _, want := range []string{"BCLONE_COMMIT", "refs/tags/$BCLONE_TAG", "rev-parse 'FETCH_HEAD^{commit}'", "RCLONE_ANDROID_API=\"26\"", "rclone-build-receipt.json"} {
		if !strings.Contains(string(script), want) {
			t.Errorf("source pin missing %s", want)
		}
	}
	if strings.Contains(string(script), "/releases/latest") && !strings.Contains(string(script), "Never resolve releases/latest") {
		t.Fatal("mutable releases/latest dependency")
	}
	for _, rel := range []string{"../../scripts/tmux/build-static-android-arm64.sh", "../../scripts/tmux/verify-static-android-arm64.sh"} {
		text, err := os.ReadFile(rel)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(string(text), "26") {
			t.Errorf("tmux missing API26 marker %s", rel)
		}
	}
}
