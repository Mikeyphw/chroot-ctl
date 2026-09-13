package arch

import "testing"

func TestCHR11ArchRejectsNonArm64RootFS(t *testing.T) {
	if _, err := RootFSURLForArch("amd64"); err == nil {
		t.Fatal("expected arch amd64 rootfs request to be rejected")
	}
	if url, err := RootFSURLForArch("arm64"); err != nil || url == "" {
		t.Fatalf("expected arm64 URL, got %q err=%v", url, err)
	}
}
