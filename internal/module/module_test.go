package module

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func fakeRuntime(t *testing.T) string {
	t.Helper()
	d := t.TempDir()
	b := filepath.Join(d, "chrootctl")
	os.WriteFile(b, append([]byte{0x7f, 'E', 'L', 'F'}, []byte("fake")...), 0755)
	sum, _ := shaFile(b)
	m := runtimeManifest{SchemaVersion: 2, RuntimeKind: "go-native", Platform: "android", ABI: "arm64-v8a", Entrypoint: "chrootctl", BackendVersion: "0.11.0", BridgeProtocolVersion: 1, Files: []runtimeFile{{Path: "chrootctl", Size: 8, SHA256: sum, Executable: true}}}
	raw, _ := json.Marshal(m)
	os.WriteFile(filepath.Join(d, "runtime-manifest.json"), raw, 0644)
	return d
}
func TestRenderGoNativeModule(t *testing.T) {
	r := fakeRuntime(t)
	out := filepath.Join(t.TempDir(), "module")
	z := filepath.Join(t.TempDir(), "module.zip")
	if e := Render(Options{OutputDir: out, ZipPath: z, NativeRuntimeDir: r, StartupTargets: []string{"work"}}); e != nil {
		t.Fatal(e)
	}
	if e := ValidateRendered(out); e != nil {
		t.Fatal(e)
	}
	if _, e := os.Stat(z); e != nil {
		t.Fatal(e)
	}
	raw, _ := os.ReadFile(filepath.Join(out, "system/bin/chrootctl"))
	if string(raw) == "" {
		t.Fatal("empty launcher")
	}
}
func TestCompatibilityPayloadGO12(t *testing.T) {
	p := CompatibilityPayload()
	if p["schemaVersion"] != 2 {
		t.Fatalf("schema=%v", p["schemaVersion"])
	}
	if _, ok := p["pythonPackage"]; !ok {
		t.Fatal("GO12 compatibility shim missing")
	}
}
