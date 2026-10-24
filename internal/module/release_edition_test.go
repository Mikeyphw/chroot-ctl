package module

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func setEditionFixture(t *testing.T, dir, edition string) {
	t.Helper()
	p := filepath.Join(dir, "runtime-manifest.json")
	raw, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	var m runtimeManifest
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	m.Edition = edition
	m.AndroidAPI = 26
	raw, err = json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, raw, 0644); err != nil {
		t.Fatal(err)
	}
}

func TestStandardEditionNoRcloneAndSealedDescriptor(t *testing.T) {
	r := fakeRuntime(t)
	setEditionFixture(t, r, "standard")
	if err := ValidateRuntime(r); err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(t.TempDir(), "standard")
	z := filepath.Join(t.TempDir(), "standard.zip")
	if err := Render(Options{OutputDir: out, ZipPath: z, NativeRuntimeDir: r}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateRendered(out); err != nil {
		t.Fatal(err)
	}
	if err := ValidateZipArchive(z); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(filepath.Join(out, "runtime", RuntimeABI, "rclone")); !os.IsNotExist(err) {
		t.Fatalf("standard leaked rclone: %v", err)
	}
	list, _ := os.ReadFile(filepath.Join(out, filepath.FromSlash(RuntimeExecutablesListPath)))
	if strings.Contains(string(list), "rclone") {
		t.Fatal("standard executable inventory includes rclone")
	}
	variant, _ := os.ReadFile(filepath.Join(out, filepath.FromSlash(BuildVariantPath)))
	if !strings.Contains(string(variant), `"edition": "standard"`) {
		t.Fatalf("missing edition descriptor: %s", variant)
	}
	if err := os.Remove(filepath.Join(out, filepath.FromSlash(BuildVariantPath))); err != nil {
		t.Fatal(err)
	}
	if err := ValidateRendered(out); err == nil {
		t.Fatal("missing edition descriptor accepted")
	}
}

func TestEditionRuntimeRejectsMixedInventory(t *testing.T) {
	r := fakeRuntime(t)
	setEditionFixture(t, r, "rclone")
	if err := ValidateRuntime(r); err == nil {
		t.Fatal("rclone edition without rclone accepted")
	}
	r2 := fakeRuntime(t)
	payload := fakeAndroidArm64ELF(183)
	path := filepath.Join(r2, "rclone")
	if err := os.WriteFile(path, payload, 0755); err != nil {
		t.Fatal(err)
	}
	raw, _ := os.ReadFile(filepath.Join(r2, "runtime-manifest.json"))
	var manifest runtimeManifest
	if err := json.Unmarshal(raw, &manifest); err != nil {
		t.Fatal(err)
	}
	sum, _ := shaFile(path)
	manifest.Files = append(manifest.Files, runtimeFile{Path: "rclone", SHA256: sum, Size: int64(len(payload)), Executable: true})
	manifest.Edition = "standard"
	manifest.AndroidAPI = 26
	raw, _ = json.Marshal(manifest)
	if err := os.WriteFile(filepath.Join(r2, "runtime-manifest.json"), raw, 0644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateRuntime(r2); err == nil {
		t.Fatal("standard edition with rclone accepted")
	}
	manifest.Edition = "rclone"
	manifest.AndroidAPI = 24
	raw, _ = json.Marshal(manifest)
	if err := os.WriteFile(filepath.Join(r2, "runtime-manifest.json"), raw, 0644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateRuntime(r2); err == nil {
		t.Fatal("edition with API24 accepted")
	}
}
