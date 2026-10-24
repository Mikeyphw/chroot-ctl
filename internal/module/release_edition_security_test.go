package module

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func renderSecurityEdition(t *testing.T, edition, target string) string {
	t.Helper()
	runtime := fakeRuntime(t)
	if edition == "rclone" {
		binary := fakeAndroidArm64ELF(183)
		path := filepath.Join(runtime, "rclone")
		if err := os.WriteFile(path, binary, 0755); err != nil {
			t.Fatal(err)
		}
		raw, err := os.ReadFile(filepath.Join(runtime, "runtime-manifest.json"))
		if err != nil {
			t.Fatal(err)
		}
		var manifest runtimeManifest
		if err := json.Unmarshal(raw, &manifest); err != nil {
			t.Fatal(err)
		}
		manifest.Files = append(manifest.Files, runtimeFile{Path: "rclone", Size: int64(len(binary)), SHA256: shaBytes(binary), Executable: true})
		raw, err = json.Marshal(manifest)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(runtime, "runtime-manifest.json"), raw, 0644); err != nil {
			t.Fatal(err)
		}
	}
	setEditionFixture(t, runtime, edition)
	out := filepath.Join(t.TempDir(), edition)
	if err := Render(Options{OutputDir: out, NativeRuntimeDir: runtime, StartupTargets: []string{target}}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateInstalled(out); err != nil {
		t.Fatalf("validate installed %s: %v", edition, err)
	}
	return out
}

func runCustomizeFixture(t *testing.T, stage, active, state, replacement string) (string, error) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(stage, "customize.sh"))
	if err != nil {
		t.Fatal(err)
	}
	script := string(raw)
	script = strings.Replace(script, `ACTIVE_MODULE="/data/adb/modules/chrootctl"`, `ACTIVE_MODULE="`+active+`"`, 1)
	if replacement != "" {
		needle := `mv "$LIVE_NEXT" "$ACTIVE_MODULE" && runtime_integrity_ready "$ACTIVE_MODULE"; then`
		if !strings.Contains(script, needle) {
			t.Fatalf("missing live swap check for fault injection")
		}
		script = strings.Replace(script, needle, replacement, 1)
	}
	local := filepath.Join(t.TempDir(), "customize.sh")
	if err := os.WriteFile(local, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("sh", local)
	cmd.Env = append(os.Environ(), "MODPATH="+stage, "CHROOTCTL_STATE_ROOT="+state)
	out, e := cmd.CombinedOutput()
	return string(out), e
}

func TestCC04ChecksumsAndInstalledEditionTamperFailClosed(t *testing.T) {
	standard := renderSecurityEdition(t, "standard", "one")
	manifest := filepath.Join(standard, "runtime", RuntimeABI, "runtime-manifest.json")
	list := filepath.Join(standard, filepath.FromSlash(RuntimeChecksumListPath))
	raw, err := os.ReadFile(manifest)
	if err != nil {
		t.Fatal(err)
	}
	expected, err := runtimeChecksumListFromManifest(raw)
	if err != nil {
		t.Fatal(err)
	}
	contents, err := os.ReadFile(list)
	if err != nil {
		t.Fatal(err)
	}
	if string(contents) != expected || !strings.Contains(expected, "  runtime-manifest.json\n") {
		t.Fatalf("runtime checksum list incomplete/mismatched: %s", contents)
	}
	if err := os.WriteFile(list, []byte("0"+string(contents[1:])), 0644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateRendered(standard); err == nil {
		t.Fatal("tampered checksum inventory accepted")
	}
	if err := ValidateInstalled(standard); err == nil {
		t.Fatal("tampered installed checksum inventory accepted")
	}
	if err := os.WriteFile(list, contents, 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(standard, filepath.FromSlash(BuildVariantPath))); err != nil {
		t.Fatal(err)
	}
	if err := ValidateInstalled(standard); err == nil {
		t.Fatal("installed release without edition descriptor accepted")
	}
	if err := os.WriteFile(filepath.Join(standard, filepath.FromSlash(BuildVariantPath)), []byte(`{"edition":"rclone"}`), 0644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateInstalled(standard); err == nil {
		t.Fatal("installed mismatched edition accepted")
	}
}

func TestCC04InstallerHashCheckRejectsCorruptionAndUnexpectedRclone(t *testing.T) {
	stage := renderSecurityEdition(t, "standard", "one")
	state := t.TempDir()
	active := filepath.Join(t.TempDir(), "inactive")
	out, err := runCustomizeFixture(t, stage, active, state, "")
	if err != nil {
		t.Fatalf("clean standard installer rejected: %v: %s", err, out)
	}
	binary := filepath.Join(stage, "runtime", RuntimeABI, "chrootctl")
	raw, err := os.ReadFile(binary)
	if err != nil {
		t.Fatal(err)
	}
	raw[len(raw)-1] ^= 0x1
	if err := os.WriteFile(binary, raw, 0755); err != nil {
		t.Fatal(err)
	}
	out, err = runCustomizeFixture(t, stage, active, state, "")
	if err == nil {
		t.Fatalf("installer accepted mutated sealed runtime: %s", out)
	}

	clean := renderSecurityEdition(t, "standard", "one")
	rclone := filepath.Join(clean, "runtime", RuntimeABI, "rclone")
	if err := os.WriteFile(rclone, []byte("stale binary"), 0755); err != nil {
		t.Fatal(err)
	}
	out, err = runCustomizeFixture(t, clean, active, state, "")
	if err == nil {
		t.Fatalf("standard installer accepted unlisted stale rclone: %s", out)
	}
}

func TestCC04SwitchDefersLiveSwapAndPreservesCurrentModule(t *testing.T) {
	for _, tc := range []struct{ oldEdition, newEdition string }{{"rclone", "standard"}, {"standard", "rclone"}} {
		t.Run(tc.oldEdition+"-to-"+tc.newEdition, func(t *testing.T) {
			stage := renderSecurityEdition(t, tc.newEdition, "new")
			activeSource := renderSecurityEdition(t, tc.oldEdition, "old")
			active := filepath.Join(t.TempDir(), "chrootctl")
			if err := os.Rename(activeSource, active); err != nil {
				t.Fatal(err)
			}
			oldManifest, err := os.ReadFile(filepath.Join(active, "runtime", RuntimeABI, "runtime-manifest.json"))
			if err != nil {
				t.Fatal(err)
			}
			marker := filepath.Join(active, "disable")
			if err := os.WriteFile(marker, []byte(""), 0600); err != nil {
				t.Fatal(err)
			}
			out, err := runCustomizeFixture(t, stage, active, t.TempDir(), "")
			if err != nil {
				t.Fatalf("staged install failed: %v: %s", err, out)
			}
			if !strings.Contains(out, "reboot required") {
				t.Fatalf("cross-edition swap was not deferred: %q", out)
			}
			got, err := os.ReadFile(filepath.Join(active, "runtime", RuntimeABI, "runtime-manifest.json"))
			if err != nil || !bytes.Equal(oldManifest, got) {
				t.Fatal("active edition was mutated before reboot")
			}
			if _, err := os.Stat(marker); err != nil {
				t.Fatal("root-manager marker lost: ", err)
			}
			if err := ValidateInstalled(active); err != nil {
				t.Fatalf("old active module invalid after transition: %v", err)
			}
			if err := ValidateInstalled(stage); err != nil {
				t.Fatalf("staged new module invalid: %v", err)
			}
			if tc.newEdition == "standard" {
				if _, err := os.Stat(filepath.Join(stage, "runtime", RuntimeABI, "rclone")); !os.IsNotExist(err) {
					t.Fatalf("staged standard retains rclone: %v", err)
				}
			}
		})
	}
}

func TestCC04LiveSwapFailureRestoresPreviousVersion(t *testing.T) {
	stage := renderSecurityEdition(t, "standard", "new")
	old := renderSecurityEdition(t, "standard", "old")
	active := filepath.Join(t.TempDir(), "chrootctl")
	if err := os.Rename(old, active); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(active, "disable")
	if err := os.WriteFile(marker, []byte(""), 0600); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(filepath.Join(active, "config/chrootctl/boot_targets.json"))
	if err != nil {
		t.Fatal(err)
	}
	out, err := runCustomizeFixture(t, stage, active, t.TempDir(), `mv "$LIVE_NEXT" "$ACTIVE_MODULE" && false; then`)
	// An installer can leave the package staged after a live-activation fault;
	// it must never claim that its active instance switched successfully.
	if err != nil {
		t.Fatalf("safe staged fallback should not itself fail: %v: %s", err, out)
	}
	after, err := os.ReadFile(filepath.Join(active, "config/chrootctl/boot_targets.json"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Fatalf("old active module lost on live swap failure: %s", out)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatal("manager marker lost: ", err)
	}
	if err := ValidateInstalled(active); err != nil {
		t.Fatalf("rollback left invalid active module: %v", err)
	}
	if !strings.Contains(out, "staged update") {
		t.Fatalf("failed swap incorrectly reported success: %s", out)
	}
}

func TestCC04HostReleaseIdentityIsVersionedAndResealCannotHideTamper(t *testing.T) {
	runtime := fakeRuntime(t)
	setEditionFixture(t, runtime, "standard")
	identity := &ReleaseIdentity{
		SourceCommit: strings.Repeat("1", 40), SourceTree: strings.Repeat("2", 40),
		DevtoolCommit: strings.Repeat("3", 40), BcloneLockSHA256: strings.Repeat("4", 64),
		GoCompilerVersion: "go1.27.2",
	}
	out := filepath.Join(t.TempDir(), "module")
	zipPath := filepath.Join(t.TempDir(), "standard.zip")
	if err := Render(Options{OutputDir: out, ZipPath: zipPath, NativeRuntimeDir: runtime, ReleaseIdentity: identity}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateZipArchive(zipPath); err != nil {
		t.Fatal(err)
	}
	if err := ValidateInstalled(out); err != nil {
		t.Fatal(err)
	}
	p := filepath.Join(out, filepath.FromSlash(BuildVariantPath))
	raw, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	var descriptor map[string]any
	if err := json.Unmarshal(raw, &descriptor); err != nil {
		t.Fatal(err)
	}
	if descriptor["schemaVersion"] != float64(2) || descriptor["devtoolCommit"] != identity.DevtoolCommit {
		t.Fatalf("release identity not emitted: %v", descriptor)
	}
	delete(descriptor, "sourceTree")
	raw, err = json.Marshal(descriptor)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, raw, 0644); err != nil {
		t.Fatal(err)
	}
	if err := writePackageManifest(out, nil); err != nil {
		t.Fatal(err)
	}
	if err := ValidateRendered(out); err == nil {
		t.Fatal("self-consistently resealed identity missing sourceTree accepted")
	}
	if err := ValidateInstalled(out); err == nil {
		t.Fatal("installed identity missing sourceTree accepted")
	}
}

func TestCC04ZipRejectsSelfConsistentlyResealedBadRuntimeChecksums(t *testing.T) {
	runtime := fakeRuntime(t)
	setEditionFixture(t, runtime, "standard")
	root := filepath.Join(t.TempDir(), "module")
	valid := filepath.Join(t.TempDir(), "good.zip")
	if err := Render(Options{OutputDir: root, ZipPath: valid, NativeRuntimeDir: runtime}); err != nil {
		t.Fatal(err)
	}
	zr, err := zip.OpenReader(valid)
	if err != nil {
		t.Fatal(err)
	}
	defer zr.Close()
	rawFiles := map[string][]byte{}
	modes := map[string]os.FileMode{}
	for _, f := range zr.File {
		rd, e := f.Open()
		if e != nil {
			t.Fatal(e)
		}
		b, e := io.ReadAll(rd)
		rd.Close()
		if e != nil {
			t.Fatal(e)
		}
		rawFiles[f.Name] = b
		modes[f.Name] = f.Mode()
	}
	content := rawFiles[RuntimeChecksumListPath]
	changed := append([]byte{}, content...)
	if changed[0] == '0' {
		changed[0] = '1'
	} else {
		changed[0] = '0'
	}
	rawFiles[RuntimeChecksumListPath] = changed
	var seal modulePackageManifest
	if err := json.Unmarshal(rawFiles[ModulePackageManifestPath], &seal); err != nil {
		t.Fatal(err)
	}
	for i := range seal.Files {
		if seal.Files[i].Path == RuntimeChecksumListPath {
			seal.Files[i].SHA256 = shaBytes(changed)
			seal.Files[i].Size = int64(len(changed))
		}
	}
	rawFiles[ModulePackageManifestPath], err = json.Marshal(seal)
	if err != nil {
		t.Fatal(err)
	}
	bad := filepath.Join(t.TempDir(), "bad-resealed.zip")
	out, err := os.Create(bad)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(out)
	for name, data := range rawFiles {
		h := &zip.FileHeader{Name: name, Method: zip.Deflate}
		h.SetMode(modes[name])
		w, e := zw.CreateHeader(h)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = w.Write(data); e != nil {
			t.Fatal(e)
		}
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := out.Close(); err != nil {
		t.Fatal(err)
	}
	err = ValidateZipArchive(bad)
	if err == nil || !strings.Contains(err.Error(), "runtime SHA-256 installer inventory") {
		t.Fatalf("resealed malicious checksum inventory not detected: %v", err)
	}
}

func TestCC04SameEditionVerifiedLiveUpdatePreservesMarker(t *testing.T) {
	staged := renderSecurityEdition(t, "standard", "new")
	old := renderSecurityEdition(t, "standard", "old")
	active := filepath.Join(t.TempDir(), "chrootctl")
	if err := os.Rename(old, active); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(active, "disable"), []byte(""), 0600); err != nil {
		t.Fatal(err)
	}
	out, err := runCustomizeFixture(t, staged, active, t.TempDir(), "")
	if err != nil {
		t.Fatalf("verified same-edition update failed: %v: %s", err, out)
	}
	if !strings.Contains(out, "runtime files updated live") {
		t.Fatalf("same edition failed to activate: %s", out)
	}
	if _, err := os.Stat(filepath.Join(active, "disable")); err != nil {
		t.Fatal("root manager disable marker lost", err)
	}
	boot, err := os.ReadFile(filepath.Join(active, "config/chrootctl/boot_targets.json"))
	if err != nil || !strings.Contains(string(boot), "new") {
		t.Fatalf("active files not updated: %v %q", err, boot)
	}
	if err := ValidateInstalled(active); err != nil {
		t.Fatalf("live updated tree invalid: %v", err)
	}
}

func TestCC04InterruptedSwapOrUnverifiedOldDisablesLiveActivation(t *testing.T) {
	for _, tc := range []string{"stale-swap", "bad-old-hash"} {
		t.Run(tc, func(t *testing.T) {
			staged := renderSecurityEdition(t, "standard", "new")
			old := renderSecurityEdition(t, "standard", "old")
			parent := t.TempDir()
			active := filepath.Join(parent, "chrootctl")
			if err := os.Rename(old, active); err != nil {
				t.Fatal(err)
			}
			before, err := os.ReadFile(filepath.Join(active, "config/chrootctl/boot_targets.json"))
			if err != nil {
				t.Fatal(err)
			}
			if tc == "stale-swap" {
				if err := os.Mkdir(filepath.Join(parent, ".chrootctl.live-old.123"), 0700); err != nil {
					t.Fatal(err)
				}
			} else {
				p := filepath.Join(active, RuntimeChecksumListPath)
				if err := os.WriteFile(p, []byte("corrupt checksum\n"), 0644); err != nil {
					t.Fatal(err)
				}
			}
			out, err := runCustomizeFixture(t, staged, active, t.TempDir(), "")
			if err != nil {
				t.Fatalf("should preserve staged reboot fallback: %v: %s", err, out)
			}
			if !strings.Contains(out, "refusing") && !strings.Contains(out, "keeping active tree") {
				t.Fatalf("missing explicit failure reason: %s", out)
			}
			after, err := os.ReadFile(filepath.Join(active, "config/chrootctl/boot_targets.json"))
			if err != nil || !bytes.Equal(before, after) {
				t.Fatalf("unsafe mutation of old active tree: %v %s", err, out)
			}
		})
	}
}
