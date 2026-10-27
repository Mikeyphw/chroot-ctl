package rcloneops

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The fixture follows the installed Skybind API-01 manifest shape. Its files
// are not a claim of a signed, provider-qualified Android runtime.
type skybindFixture struct {
	layout     skybindLayout
	manifest   skybindInstalledManifest
	provenance skybindRuntimeProvenance
	owner      uint32
}

func skybindFixtureFile(t *testing.T, file, body string, mode os.FileMode) {
	t.Helper()
	if err := os.WriteFile(file, []byte(body), mode); err != nil {
		t.Fatal(err)
	}
}

func fixtureDigest(body []byte) string {
	digest := sha256.Sum256(body)
	return hex.EncodeToString(digest[:])
}

func (f *skybindFixture) add(t *testing.T, rel, body string, mode os.FileMode, provenance bool) {
	t.Helper()
	path := filepath.Join(f.layout.moduleDir, rel)
	skybindFixtureFile(t, path, body, mode)
	rec := skybindFileRecord{SHA256: fixtureDigest([]byte(body)), Size: int64(len(body))}
	f.manifest.Files[rel] = rec
	if provenance {
		f.provenance.Files[rel] = rec
	}
}

func (f *skybindFixture) seal(t *testing.T) {
	t.Helper()
	raw, e := json.Marshal(f.provenance)
	if e != nil {
		t.Fatal(e)
	}
	f.add(t, "runtime.provenance.json", string(raw), 0600, false)
	f.manifest.ProvenanceSHA = fixtureDigest(raw)
	raw, e = json.Marshal(f.manifest)
	if e != nil {
		t.Fatal(e)
	}
	skybindFixtureFile(t, filepath.Join(f.layout.moduleDir, "skybind.manifest.json"), string(raw), 0600)
}

func newSkybindFixture(t *testing.T) *skybindFixture {
	t.Helper()
	root := t.TempDir()
	f := &skybindFixture{
		layout:     skybindLayout{moduleDir: filepath.Join(root, "modules", "skybind"), configDir: filepath.Join(root, "config")},
		owner:      uint32(os.Geteuid()),
		manifest:   skybindInstalledManifest{SchemaVersion: 1, Product: "skybind", Qualification: "CANDIDATE_ONLY_NOT_SEALED", Files: map[string]skybindFileRecord{}},
		provenance: skybindRuntimeProvenance{SchemaVersion: 1, Product: "Skybind", Arch: "arm64", EnginePath: "system/bin/skybind-rclone-engine", Files: map[string]skybindFileRecord{}},
	}
	for _, dir := range []string{filepath.Join(root, "modules"), f.layout.moduleDir, filepath.Join(f.layout.moduleDir, "system"), filepath.Join(f.layout.moduleDir, "system/bin"), f.layout.configDir} {
		if e := os.Mkdir(dir, 0700); e != nil {
			t.Fatal(e)
		}
	}
	f.add(t, "module.prop", "id=skybind\nname=Skybind\n", 0600, false)
	f.add(t, "system/bin/skybind-rclone", "#!/system/bin/sh\nexec /fake/bin/rclone \"$@\"\n", 0700, true)
	f.add(t, "system/bin/rclone", "#!/system/bin/sh\nexec /fake/bin/rclone \"$@\"\n", 0700, true)
	arm64 := make([]byte, 64)
	copy(arm64, []byte("\x7fELF"))
	arm64[4], arm64[5], arm64[6] = 2, 1, 1
	arm64[18], arm64[19] = 0xb7, 0
	f.add(t, "system/bin/skybind-rclone-engine", string(arm64), 0700, true)
	skybindFixtureFile(t, filepath.Join(f.layout.configDir, "rclone.conf"), "[test]\ntype = local\n", 0600)
	f.seal(t)
	return f
}

func TestSkybindExplicitProviderVerifiedInstalledFixture(t *testing.T) {
	f := newSkybindFixture(t)
	runtime, e := skybindRuntimeAt(f.layout, f.owner)
	if e != nil {
		t.Fatalf("source-bound fixture refused: %v", e)
	}
	if runtime.Provider != "skybind" || runtime.Executable != filepath.Join(f.layout.moduleDir, "system/bin/skybind-rclone") || runtime.Config != filepath.Join(f.layout.configDir, "rclone.conf") {
		t.Fatalf("wrong selection: %+v", runtime)
	}
}

func TestSkybindRefusesModifiedOrUnsafeInstalledFiles(t *testing.T) {
	tests := []struct {
		name   string
		modify func(*testing.T, *skybindFixture)
	}{
		{"different-module", func(t *testing.T, f *skybindFixture) {
			skybindFixtureFile(t, filepath.Join(f.layout.moduleDir, "module.prop"), "id=not-skybind\n", 0600)
		}},
		{"engine-modified", func(t *testing.T, f *skybindFixture) {
			skybindFixtureFile(t, filepath.Join(f.layout.moduleDir, "system/bin/skybind-rclone-engine"), "replaced engine", 0700)
		}},
		{"wrapper-modified", func(t *testing.T, f *skybindFixture) {
			skybindFixtureFile(t, filepath.Join(f.layout.moduleDir, "system/bin/skybind-rclone"), "replaced launcher", 0700)
		}},
		{"wrong-provenance-hash", func(t *testing.T, f *skybindFixture) {
			f.manifest.ProvenanceSHA = strings.Repeat("0", 64)
			raw, _ := json.Marshal(f.manifest)
			skybindFixtureFile(t, filepath.Join(f.layout.moduleDir, "skybind.manifest.json"), string(raw), 0600)
		}},
		{"wrong-product", func(t *testing.T, f *skybindFixture) {
			f.manifest.Product = "other"
			raw, _ := json.Marshal(f.manifest)
			skybindFixtureFile(t, filepath.Join(f.layout.moduleDir, "skybind.manifest.json"), string(raw), 0600)
		}},
		{"wrong-abi", func(t *testing.T, f *skybindFixture) { f.provenance.Arch = "amd64"; f.seal(t) }},
		{"wrong-engine-path", func(t *testing.T, f *skybindFixture) { f.provenance.EnginePath = "system/bin/rclone"; f.seal(t) }},
		{"alias-does-not-match-wrapper", func(t *testing.T, f *skybindFixture) {
			f.add(t, "system/bin/skybind-rclone", "#!/system/bin/sh\nexit 1\n", 0700, true)
			f.seal(t)
		}},
		{"engine-wrong-architecture", func(t *testing.T, f *skybindFixture) {
			x := make([]byte, 64)
			copy(x, []byte("\x7fELF"))
			x[4], x[5], x[6] = 2, 1, 1
			x[18] = 0x3e
			f.add(t, "system/bin/skybind-rclone-engine", string(x), 0700, true)
			f.seal(t)
		}},
		{"missing-config", func(t *testing.T, f *skybindFixture) {
			if e := os.Remove(filepath.Join(f.layout.configDir, "rclone.conf")); e != nil {
				t.Fatal(e)
			}
		}},
		{"credential-world-readable", func(t *testing.T, f *skybindFixture) {
			if e := os.Chmod(filepath.Join(f.layout.configDir, "rclone.conf"), 0644); e != nil {
				t.Fatal(e)
			}
		}},
		{"credential-symlink", func(t *testing.T, f *skybindFixture) {
			p := filepath.Join(f.layout.configDir, "rclone.conf")
			if e := os.Rename(p, p+".real"); e != nil {
				t.Fatal(e)
			}
			if e := os.Symlink(p+".real", p); e != nil {
				t.Fatal(e)
			}
		}},
		{"world-writable-dir", func(t *testing.T, f *skybindFixture) {
			if e := os.Chmod(filepath.Join(f.layout.moduleDir, "system"), 0777); e != nil {
				t.Fatal(e)
			}
		}},
		{"wrapper-symlink", func(t *testing.T, f *skybindFixture) {
			p := filepath.Join(f.layout.moduleDir, "system/bin/skybind-rclone")
			if e := os.Remove(p); e != nil {
				t.Fatal(e)
			}
			if e := os.Symlink(filepath.Join(f.layout.moduleDir, "system/bin/rclone"), p); e != nil {
				t.Fatal(e)
			}
		}},
		{"nonexecutable-wrapper", func(t *testing.T, f *skybindFixture) {
			if e := os.Chmod(filepath.Join(f.layout.moduleDir, "system/bin/skybind-rclone"), 0600); e != nil {
				t.Fatal(e)
			}
		}},
		{"nonexecutable-engine", func(t *testing.T, f *skybindFixture) {
			if e := os.Chmod(filepath.Join(f.layout.moduleDir, "system/bin/skybind-rclone-engine"), 0600); e != nil {
				t.Fatal(e)
			}
		}},
		{"unapproved-file-owner", func(t *testing.T, f *skybindFixture) { f.owner = uint32(os.Geteuid() + 1) }},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			f := newSkybindFixture(t)
			tc.modify(t, f)
			if _, e := skybindRuntimeAt(f.layout, f.owner); e == nil {
				t.Fatal("unsafe fixture was accepted")
			}
		})
	}
}

func TestSkybindNeverImplicitlySelectsOrFallsBack(t *testing.T) {
	for _, tc := range []struct {
		name string
		env  []string
	}{
		{"unknown-provider", []string{"CHROOTCTL_RCLONE_PROVIDER=invented"}},
		{"skybind-no-fallback", []string{"CHROOTCTL_RCLONE_PROVIDER=skybind"}},
		{"skybind-no-manual-path", []string{"CHROOTCTL_RCLONE_PROVIDER=skybind", "CHROOTCTL_RCLONE_PATH=/bin/true"}},
		{"skybind-no-config-override", []string{"CHROOTCTL_RCLONE_PROVIDER=skybind", "CHROOTCTL_RCLONE_CONFIG=/tmp/unsafe"}},
		{"skybind-no-path-optin", []string{"CHROOTCTL_RCLONE_PROVIDER=skybind", "CHROOTCTL_RCLONE_ALLOW_PATH=1"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, e := RuntimeFromEnviron(tc.env)
			if e == nil {
				t.Fatal("provider selection unexpectedly succeeded")
			}
		})
	}
}

func TestPrivatePersistentProviderSelection(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "provider")
	owner := uint32(os.Geteuid())
	cases := []struct {
		name, body string
		mode       os.FileMode
		valid      bool
	}{
		{"skybind", "skybind\n", 0600, true},
		{"native", "chrootctl\n", 0600, true},
		{"invalid", "automatic\n", 0600, false},
		{"malformed", "skybind\nchrootctl\n", 0600, false},
		{"public-file", "skybind\n", 0644, false},
		{"empty", "", 0600, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if e := os.WriteFile(path, []byte(tc.body), tc.mode); e != nil {
				t.Fatal(e)
			}
			if e := os.Chmod(path, tc.mode); e != nil {
				t.Fatal(e)
			}
			got, e := readRcloneProviderSelection(path, owner)
			if tc.valid && (e != nil || got != strings.TrimSuffix(tc.body, "\n")) {
				t.Fatalf("want valid choice; got %q: %v", got, e)
			}
			if !tc.valid && e == nil {
				t.Fatal("invalid persistent choice accepted")
			}
		})
	}
	if e := os.Remove(path); e != nil {
		t.Fatal(e)
	}
	if e := os.Symlink("/dev/null", path); e != nil {
		t.Fatal(e)
	}
	if _, e := readRcloneProviderSelection(path, owner); e == nil {
		t.Fatal("symlink choice accepted")
	}
}

func TestSkybindProviderPreventsChrootctlCredentialImport(t *testing.T) {
	t.Setenv("CHROOTCTL_RCLONE_PROVIDER", "skybind")
	_, e := ImportConfig("/no-such-staged-file")
	if e == nil || !strings.Contains(e.Error(), "Skybind owns") {
		t.Fatalf("unexpected import result: %v", e)
	}
}
