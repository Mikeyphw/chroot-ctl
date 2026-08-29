package module

import (
	"encoding/binary"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func fakeAndroidArm64ELF(machine uint16) []byte {
	interp := append([]byte("/system/bin/linker64"), 0)
	b := make([]byte, 64+56+len(interp))
	copy(b[:4], []byte{0x7f, 'E', 'L', 'F'})
	b[4], b[5], b[6] = 2, 1, 1                 // ELF64, little-endian, current version
	binary.LittleEndian.PutUint16(b[16:18], 3) // ET_DYN / PIE
	binary.LittleEndian.PutUint16(b[18:20], machine)
	binary.LittleEndian.PutUint32(b[20:24], 1)
	binary.LittleEndian.PutUint64(b[32:40], 64)
	binary.LittleEndian.PutUint16(b[52:54], 64)
	binary.LittleEndian.PutUint16(b[54:56], 56)
	binary.LittleEndian.PutUint16(b[56:58], 1)
	ph := b[64:120]
	binary.LittleEndian.PutUint32(ph[0:4], 3) // PT_INTERP
	binary.LittleEndian.PutUint32(ph[4:8], 4) // PF_R
	binary.LittleEndian.PutUint64(ph[8:16], 120)
	binary.LittleEndian.PutUint64(ph[32:40], uint64(len(interp)))
	binary.LittleEndian.PutUint64(ph[40:48], uint64(len(interp)))
	binary.LittleEndian.PutUint64(ph[48:56], 1)
	copy(b[120:], interp)
	return b
}

func writeFakeRuntime(t *testing.T, machine uint16) string {
	t.Helper()
	d := t.TempDir()
	b := filepath.Join(d, "chrootctl")
	payload := fakeAndroidArm64ELF(machine)
	if err := os.WriteFile(b, payload, 0755); err != nil {
		t.Fatal(err)
	}
	sum, _ := shaFile(b)
	m := runtimeManifest{SchemaVersion: 2, RuntimeKind: "go-native", Platform: "android", ABI: "arm64-v8a", Entrypoint: "chrootctl", BackendVersion: "0.11.0", BridgeProtocolVersion: 1, Files: []runtimeFile{{Path: "chrootctl", Size: int64(len(payload)), SHA256: sum, Executable: true}}}
	raw, _ := json.Marshal(m)
	if err := os.WriteFile(filepath.Join(d, "runtime-manifest.json"), raw, 0644); err != nil {
		t.Fatal(err)
	}
	return d
}

func fakeRuntime(t *testing.T) string { return writeFakeRuntime(t, 183) }
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

	serviceRaw, _ := os.ReadFile(filepath.Join(out, "service.sh"))
	helperRaw, _ := os.ReadFile(filepath.Join(out, "bin/chrootctl-magisk-helper"))
	if !strings.Contains(string(serviceRaw), "__module-service 'work'") {
		t.Fatalf("module service does not pass startup target: %s", serviceRaw)
	}
	for _, want := range []string{"clipboard daemon start", "--name \"$target\" mount", "run --boot"} {
		if !strings.Contains(string(helperRaw), want) {
			t.Fatalf("module helper missing %q", want)
		}
	}
}

func TestValidateRuntimeRejectsMislabeledNonArm64ELF(t *testing.T) {
	r := writeFakeRuntime(t, 62) // EM_X86_64
	if err := ValidateRuntime(r); err == nil || !strings.Contains(err.Error(), "ELF identity mismatch") {
		t.Fatalf("expected ELF architecture rejection, got %v", err)
	}
}
func TestCompatibilityPayloadGO13(t *testing.T) {
	p := CompatibilityPayload()
	if p["schemaVersion"] != 3 {
		t.Fatalf("schema=%v", p["schemaVersion"])
	}
	if _, ok := p["pythonPackage"]; ok {
		t.Fatal("schema3 must not contain pythonPackage")
	}
	b := p["backend"].(map[string]any)
	if b["implementation"] != "go" {
		t.Fatalf("backend=%v", b)
	}
}
