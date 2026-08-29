package integrity

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestChecksumAndVerify(t *testing.T) {
	d := t.TempDir()
	p := filepath.Join(d, "rootfs.tar.gz")
	if err := os.WriteFile(p, []byte("hello"), 0o600); err != nil {
		t.Fatal(err)
	}
	sum, _ := SHA256File(p)
	m := filepath.Join(d, "SHA256SUMS")
	_ = os.WriteFile(m, []byte(sum+"  rootfs.tar.gz\n"), 0o600)
	got, err := ChecksumFromManifest(m, "rootfs.tar.gz")
	if err != nil || got != sum {
		t.Fatalf("%q %v", got, err)
	}
	if err := VerifySHA256(p, sum); err != nil {
		t.Fatal(err)
	}
	err = VerifySHA256(p, strings.Repeat("0", 64))
	if err == nil || !strings.Contains(err.Error(), "sha256 mismatch") {
		t.Fatal(err)
	}
}
func TestManifestMissing(t *testing.T) {
	p := filepath.Join(t.TempDir(), "sums")
	_ = os.WriteFile(p, []byte(strings.Repeat("a", 64)+"  other\n"), 0o600)
	if _, e := ChecksumFromManifest(p, "wanted"); e == nil {
		t.Fatal("expected error")
	}
}
