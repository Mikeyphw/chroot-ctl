package repoctl

import (
	"os"
	"regexp"
	"strings"
	"testing"
)

func TestBcloneRuntimeTracksLatestReleaseWithoutVersionPin(t *testing.T) {
	raw, err := os.ReadFile("../../scripts/install-rclone-android-runtime.sh")
	if err != nil {
		t.Fatal(err)
	}
	s := string(raw)
	for _, want := range []string{
		"BenjiThatFoxGuy/bclone",
		"/releases/latest",
		"resolve_latest_bclone_tag",
		"/archive/refs/tags",
		"go mod vendor",
		"-mod=vendor",
	} {
		if !strings.Contains(s, want) {
			t.Fatalf("latest-bclone runtime contract missing %q", want)
		}
	}
	for _, forbidden := range []string{
		"downloads.rclone.org",
		"RCLONE_SOURCE_SHA256",
		"RCLONE_VENDOR_SHA256",
	} {
		if strings.Contains(s, forbidden) {
			t.Fatalf("latest-bclone runtime still contains upstream/pinned contract %q", forbidden)
		}
	}
	if regexp.MustCompile(`(?m)readonly\s+(?:RCLONE|BCLONE)_VERSION=["']?[0-9]+\.[0-9]+\.[0-9]+`).MatchString(s) {
		t.Fatal("bclone runtime must resolve releases/latest instead of pinning a version")
	}
}

func TestCopyErrorDoesNotReintroduceExecCommand(t *testing.T) {
	raw, err := os.ReadFile("../module/webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	s := string(raw)
	if strings.Contains(strings.ToLower(s), "execcommand") {
		t.Fatal("WebUI copy action reintroduced forbidden document.execCommand")
	}
	if !strings.Contains(s, "navigator.clipboard?.writeText") {
		t.Fatal("WebUI copy action must use the Clipboard API")
	}
}
