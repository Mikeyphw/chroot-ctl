package module

import (
	"archive/zip"
	"encoding/binary"
	"encoding/json"
	"io"
	"os"
	"os/exec"
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

func TestLauncherResolvesModuleDirFromExplicitModuleTreePath(t *testing.T) {
	moduleRoot := filepath.Join(t.TempDir(), "chrootctl-magisk")
	launcherPath := filepath.Join(moduleRoot, "system/bin/chrootctl")
	runtimePath := filepath.Join(moduleRoot, "runtime/arm64-v8a/chrootctl")
	if err := os.MkdirAll(filepath.Dir(launcherPath), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(runtimePath), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(launcherPath, []byte(launcher()), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(filepath.Dir(runtimePath), "runtime-manifest.json"), []byte("{}"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(runtimePath, []byte("#!/bin/sh\necho runtime:$1:$CHROOTCTL_MODULE_DIR\n"), 0755); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("sh", launcherPath, "probe")
	cmd.Env = append(os.Environ(), "CHROOTCTL_MODULE_DIR=")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("launcher failed: %v\n%s", err, out)
	}
	want := "runtime:probe:" + moduleRoot
	if !strings.Contains(string(out), want) {
		t.Fatalf("launcher did not derive module root from $0; want %q in %q", want, out)
	}
}

func TestLauncherMissingRuntimeErrorNamesResolvedPath(t *testing.T) {
	moduleRoot := filepath.Join(t.TempDir(), "chrootctl-magisk")
	launcherPath := filepath.Join(moduleRoot, "system/bin/chrootctl")
	if err := os.MkdirAll(filepath.Dir(launcherPath), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(launcherPath, []byte(launcher()), 0755); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("sh", launcherPath)
	cmd.Env = append(os.Environ(), "CHROOTCTL_MODULE_DIR=")
	out, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatalf("launcher unexpectedly succeeded: %s", out)
	}
	text := string(out)
	for _, want := range []string{moduleRoot + "/runtime/arm64-v8a", "reboot so modules_update is promoted to modules"} {
		if !strings.Contains(text, want) {
			t.Fatalf("launcher diagnostic missing %q: %s", want, text)
		}
	}
}

func assertZipDoesNotContain(t *testing.T, zipPath string, forbidden ...string) {
	t.Helper()
	zr, err := zip.OpenReader(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	defer zr.Close()
	for _, f := range zr.File {
		for _, name := range forbidden {
			if f.Name == name || strings.Contains(f.Name, name) {
				t.Fatalf("zip %s unexpectedly contains %s", zipPath, f.Name)
			}
		}
	}
}

func TestRenderZipInsideOutputDoesNotIncludeZipItself(t *testing.T) {
	r := fakeRuntime(t)
	out := filepath.Join(t.TempDir(), "module")
	z := filepath.Join(out, "module.zip")
	if err := Render(Options{OutputDir: out, ZipPath: z, NativeRuntimeDir: r}); err != nil {
		t.Fatal(err)
	}
	assertZipDoesNotContain(t, z, "module.zip", ".chrootctl-module-")
}

func TestZipSkipsExistingDestinationInsideModuleTree(t *testing.T) {
	r := fakeRuntime(t)
	out := filepath.Join(t.TempDir(), "module")
	z := filepath.Join(out, "module.zip")
	if err := Render(Options{OutputDir: out, NativeRuntimeDir: r}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(z, []byte("stale zip placeholder"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := Zip(out, z); err != nil {
		t.Fatal(err)
	}
	assertZipDoesNotContain(t, z, "module.zip", ".chrootctl-module-")
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

func TestCHR15ModulePackageManifestSealsRenderedTree(t *testing.T) {
	r := fakeRuntime(t)
	out := filepath.Join(t.TempDir(), "module")
	if err := Render(Options{OutputDir: out, NativeRuntimeDir: r, StartupTargets: []string{"beta", "alpha", "alpha"}}); err != nil {
		t.Fatal(err)
	}
	manifestPath := filepath.Join(out, ModulePackageManifestPath)
	raw, err := os.ReadFile(manifestPath)
	if err != nil {
		t.Fatal(err)
	}
	var manifest modulePackageManifest
	if err := json.Unmarshal(raw, &manifest); err != nil {
		t.Fatal(err)
	}
	if manifest.SchemaVersion != ModulePackageSchemaVersion || manifest.ModuleID != ModuleID || manifest.ModuleVersionCode != ModuleVersionCode {
		t.Fatalf("unexpected package identity: %+v", manifest)
	}
	if strings.Join(manifest.StartupTargets, ",") != "alpha,beta" {
		t.Fatalf("startup targets were not canonicalized: %v", manifest.StartupTargets)
	}
	seen := map[string]bool{}
	for _, f := range manifest.Files {
		seen[f.Path] = true
	}
	for _, required := range []string{"uninstall.sh", "config/chrootctl/compatibility-manifest.json", "runtime/arm64-v8a/chrootctl"} {
		if !seen[required] {
			t.Fatalf("package manifest missing required file %s: %+v", required, manifest.Files)
		}
	}
	if err := ValidateRendered(out); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(out, "module.prop"), []byte("id=chrootctl-magisk\nversionCode=0\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateRendered(out); err == nil || !strings.Contains(err.Error(), "module package") {
		t.Fatalf("expected sealed manifest mismatch after tamper, got %v", err)
	}
}

func TestCHR15ValidateRenderedRejectsUnsealedExtraPayload(t *testing.T) {
	r := fakeRuntime(t)
	out := filepath.Join(t.TempDir(), "module")
	if err := Render(Options{OutputDir: out, NativeRuntimeDir: r}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(out, "unexpected-root-file"), []byte("extra"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateRendered(out); err == nil || !strings.Contains(err.Error(), "file count mismatch") {
		t.Fatalf("expected unsealed extra payload rejection, got %v", err)
	}
}

func TestCHR15ValidateZipArchiveUsesPackageSeal(t *testing.T) {
	r := fakeRuntime(t)
	out := filepath.Join(t.TempDir(), "module")
	zipPath := filepath.Join(t.TempDir(), "module.zip")
	if err := Render(Options{OutputDir: out, ZipPath: zipPath, NativeRuntimeDir: r, StartupTargets: []string{"work"}}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateZipArchive(zipPath); err != nil {
		t.Fatal(err)
	}
	badZip := filepath.Join(t.TempDir(), "bad.zip")
	zf, err := os.Create(badZip)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(zf)
	w, err := zw.Create("module.prop")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.Write([]byte("id=chrootctl-magisk\n")); err != nil {
		t.Fatal(err)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := zf.Close(); err != nil {
		t.Fatal(err)
	}
	if err := ValidateZipArchive(badZip); err == nil || !strings.Contains(err.Error(), ModulePackageManifestPath) {
		t.Fatalf("expected missing module package manifest rejection, got %v", err)
	}

	badTargetsZip := filepath.Join(t.TempDir(), "bad-targets.zip")
	good, err := zip.OpenReader(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	mutated, err := os.Create(badTargetsZip)
	if err != nil {
		good.Close()
		t.Fatal(err)
	}
	mutator := zip.NewWriter(mutated)
	for _, entry := range good.File {
		header := entry.FileHeader
		w, err := mutator.CreateHeader(&header)
		if err != nil {
			good.Close()
			t.Fatal(err)
		}
		if entry.Name == "config/chrootctl/boot_targets.json" {
			if _, err := w.Write([]byte(`{"startup_targets":["other"]}`)); err != nil {
				good.Close()
				t.Fatal(err)
			}
			continue
		}
		rc, err := entry.Open()
		if err != nil {
			good.Close()
			t.Fatal(err)
		}
		_, err = io.Copy(w, rc)
		rc.Close()
		if err != nil {
			good.Close()
			t.Fatal(err)
		}
	}
	if err := mutator.Close(); err != nil {
		good.Close()
		t.Fatal(err)
	}
	if err := mutated.Close(); err != nil {
		good.Close()
		t.Fatal(err)
	}
	if err := good.Close(); err != nil {
		t.Fatal(err)
	}
	if err := ValidateZipArchive(badTargetsZip); err == nil || !strings.Contains(err.Error(), "startup targets") {
		t.Fatalf("expected boot target/package manifest mismatch rejection, got %v", err)
	}
}
