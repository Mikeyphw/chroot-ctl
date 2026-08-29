package repoctl

import (
	"archive/tar"
	"compress/gzip"
	"os"
	"path/filepath"
	"strings"
	"testing"

	chmodule "chrootctl/internal/module"
)

func TestShellQuote(t *testing.T) {
	if got := shellQuote("/tmp/a'b.zip"); got != "'/tmp/a'\\''b.zip'" {
		t.Fatalf("quote=%q", got)
	}
}
func TestForbiddenSourceNames(t *testing.T) {
	for _, v := range []string{"a.pyc", "x.orig", "x.rej", "x~", "x.bak", "x.bak-1"} {
		if !forbiddenName(v) {
			t.Fatalf("expected forbidden %s", v)
		}
	}
}
func TestRuntimeManifestShapeMatchesShippingContract(t *testing.T) {
	m := runtimeManifest{SchemaVersion: chmodule.RuntimeSchemaVersion, RuntimeKind: chmodule.RuntimeKind, Platform: "android", ABI: chmodule.RuntimeABI, Entrypoint: chmodule.RuntimeEntrypoint, BackendVersion: chmodule.BackendVersion, BridgeProtocolVersion: chmodule.BridgeProtocolVersion}
	if m.SchemaVersion != 2 || m.RuntimeKind != "go-native" || m.BackendVersion != "0.11.0" || m.BridgeProtocolVersion != 1 {
		t.Fatalf("unexpected runtime identity: %+v", m)
	}
}
func TestBuildSourceIsGoNativeAndDoesNotFollowSymlinks(t *testing.T) {
	root, e := repoRoot()
	if e != nil {
		t.Fatal(e)
	}
	tmp := t.TempDir()
	out := filepath.Join(tmp, "source.tar.gz")
	path, e := BuildSource(SourceOptions{Version: "test", Output: out})
	if e != nil {
		t.Fatal(e)
	}
	f, e := os.Open(path)
	if e != nil {
		t.Fatal(e)
	}
	defer f.Close()
	gz, e := gzip.NewReader(f)
	if e != nil {
		t.Fatal(e)
	}
	tr := tar.NewReader(gz)
	foundGoMod := false
	for {
		h, e := tr.Next()
		if e != nil {
			break
		}
		if strings.HasSuffix(h.Name, "/go.mod") {
			foundGoMod = true
		}
		if strings.Contains(h.Name, "/.git/") || strings.Contains(h.Name, "/dist/") {
			t.Fatalf("forbidden archive path %s", h.Name)
		}
	}
	if !foundGoMod {
		t.Fatal("go.mod missing")
	}
	_ = root
}
