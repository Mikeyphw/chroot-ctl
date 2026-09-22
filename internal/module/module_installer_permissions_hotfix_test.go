package module

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func runtimeWithInstallerExecutables(t *testing.T) string {
	t.Helper()
	runtime := fakeRuntime(t)
	raw, err := os.ReadFile(filepath.Join(runtime, "runtime-manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	var manifest runtimeManifest
	if err := json.Unmarshal(raw, &manifest); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"tmux", "rclone"} {
		payload := fakeAndroidArm64ELF(183)
		path := filepath.Join(runtime, name)
		if err := os.WriteFile(path, payload, 0o755); err != nil {
			t.Fatal(err)
		}
		sum, err := shaFile(path)
		if err != nil {
			t.Fatal(err)
		}
		manifest.Files = append(manifest.Files, runtimeFile{
			Path:       name,
			Size:       int64(len(payload)),
			SHA256:     sum,
			Executable: true,
		})
	}
	raw, err = json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(runtime, "runtime-manifest.json"), raw, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateRuntime(runtime); err != nil {
		t.Fatal(err)
	}
	return runtime
}

func writeInstallerStub(t *testing.T, dir, name, body string) {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte("#!/bin/sh\nset -eu\n"+body+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
}

func TestRenderCanonicalizesRuntimeModesDespiteRestrictiveUmask(t *testing.T) {
	runtime := runtimeWithInstallerExecutables(t)
	out := filepath.Join(t.TempDir(), "module")
	zipPath := filepath.Join(t.TempDir(), "module.zip")

	oldUmask := syscall.Umask(0o077)
	defer syscall.Umask(oldUmask)
	if err := Render(Options{OutputDir: out, ZipPath: zipPath, NativeRuntimeDir: runtime}); err != nil {
		t.Fatal(err)
	}

	for _, rel := range []string{"chrootctl", "rclone", "tmux"} {
		st, err := os.Stat(filepath.Join(out, "runtime", RuntimeABI, rel))
		if err != nil {
			t.Fatal(err)
		}
		if st.Mode().Perm() != 0o755 {
			t.Fatalf("rendered runtime %s mode=%04o want 0755", rel, st.Mode().Perm())
		}
	}
	for _, rel := range []string{"runtime-manifest.json", RuntimeExecutablesListPath} {
		path := filepath.Join(out, filepath.FromSlash(rel))
		if rel == "runtime-manifest.json" {
			path = filepath.Join(out, "runtime", RuntimeABI, rel)
		}
		st, err := os.Stat(path)
		if err != nil {
			t.Fatal(err)
		}
		if st.Mode().Perm() != 0o644 {
			t.Fatalf("rendered metadata %s mode=%04o want 0644", rel, st.Mode().Perm())
		}
	}

	listRaw, err := os.ReadFile(filepath.Join(out, filepath.FromSlash(RuntimeExecutablesListPath)))
	if err != nil {
		t.Fatal(err)
	}
	if got, want := string(listRaw), "chrootctl\nrclone\ntmux\n"; got != want {
		t.Fatalf("runtime executable installer inventory=%q want %q", got, want)
	}
	if err := ValidateZipArchive(zipPath); err != nil {
		t.Fatalf("ZIP mode/inventory validation failed: %v", err)
	}
}

func TestCustomizeRestoresEverySealedRuntimeExecutableAfterExtractionNormalization(t *testing.T) {
	runtime := runtimeWithInstallerExecutables(t)
	out := filepath.Join(t.TempDir(), "module")
	if err := Render(Options{OutputDir: out, NativeRuntimeDir: runtime}); err != nil {
		t.Fatal(err)
	}

	// Simulate a root manager extracting every regular file as 0644 before
	// customize.sh enforces the module's runtime executable contract.
	if err := filepath.Walk(out, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return os.Chmod(path, 0o755)
		}
		return os.Chmod(path, 0o644)
	}); err != nil {
		t.Fatal(err)
	}

	// Avoid invoking the production log helper while exercising customize.sh.
	if err := os.WriteFile(filepath.Join(out, "bin", "chrootctl-log-helper"), []byte("#!/bin/sh\nexit 0\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	stubDir := t.TempDir()
	writeInstallerStub(t, stubDir, "set_perm_recursive", `root="$1"; dmode="$4"; fmode="$5"; find "$root" -type d -exec chmod "$dmode" {} +; find "$root" -type f -exec chmod "$fmode" {} +`)
	writeInstallerStub(t, stubDir, "set_perm", `chmod "$4" "$1"`)
	writeInstallerStub(t, stubDir, "ui_print", `exit 0`)

	cmd := exec.Command("sh", filepath.Join(out, "customize.sh"))
	cmd.Env = append(os.Environ(), "MODPATH="+out, "PATH="+stubDir+string(os.PathListSeparator)+os.Getenv("PATH"))
	combined, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("customize.sh permission simulation failed: %v\n%s", err, combined)
	}

	for _, rel := range []string{"chrootctl", "rclone", "tmux"} {
		st, err := os.Stat(filepath.Join(out, "runtime", RuntimeABI, rel))
		if err != nil {
			t.Fatal(err)
		}
		if st.Mode().Perm() != 0o755 {
			t.Fatalf("installed runtime %s mode=%04o want 0755", rel, st.Mode().Perm())
		}
	}
	for _, rel := range []string{"runtime-manifest.json", "tmux-runtime-manifest.json", "tmux.sha256"} {
		path := filepath.Join(out, "runtime", RuntimeABI, rel)
		if _, err := os.Stat(path); os.IsNotExist(err) {
			continue
		}
		st, err := os.Stat(path)
		if err != nil {
			t.Fatal(err)
		}
		if st.Mode().Perm() != 0o644 {
			t.Fatalf("installed runtime metadata %s mode=%04o want 0644", rel, st.Mode().Perm())
		}
	}
	customizeRaw, err := os.ReadFile(filepath.Join(out, "customize.sh"))
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"runtime-executables.list", "restore_runtime_exec_modes", "runtime_execs_ready"} {
		if !strings.Contains(string(customizeRaw), want) {
			t.Fatalf("customize.sh missing installer permission contract %q", want)
		}
	}
}
