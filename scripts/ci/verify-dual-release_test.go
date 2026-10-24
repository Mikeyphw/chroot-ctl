//go:build ignore

package main

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func materializeDual(t *testing.T) (string, string, string) {
	t.Helper()
	root := t.TempDir()
	source := strings.Repeat("a", 40)
	devtool := strings.Repeat("b", 40)
	content := []byte("GO-BACKEND-SHARED-FIXTURE")
	for _, edition := range []string{"standard", "rclone"} {
		rt := filepath.Join(root, "runtime", edition, "arm64-v8a")
		expanded := filepath.Join(root, "module", edition)
		mustMkdir := func(dir string) {
			t.Helper()
			if e := os.MkdirAll(dir, 0755); e != nil {
				t.Fatal(e)
			}
		}
		mustWrite := func(p string, b []byte) {
			t.Helper()
			mustMkdir(filepath.Dir(p))
			if e := os.WriteFile(p, b, 0644); e != nil {
				t.Fatal(e)
			}
		}
		mustMkdir(rt)
		mustWrite(filepath.Join(rt, "chrootctl"), content)
		if e := os.Chmod(filepath.Join(rt, "chrootctl"), 0755); e != nil {
			t.Fatal(e)
		}
		files := []fileEntry{{Path: "chrootctl", Size: int64(len(content)), SHA256: hashBytes(content), Executable: true}}
		if edition == "rclone" {
			raw := []byte("RCLONE-BUNDLE-FIXTURE")
			mustWrite(filepath.Join(rt, "rclone"), raw)
			if e := os.Chmod(filepath.Join(rt, "rclone"), 0755); e != nil {
				t.Fatal(e)
			}
			files = append(files, fileEntry{Path: "rclone", Size: int64(len(raw)), SHA256: hashBytes(raw), Executable: true})
		}
		manifest, _ := json.Marshal(runtimeManifest{Edition: edition, AndroidAPI: 26, Files: files})
		mustWrite(filepath.Join(rt, "runtime-manifest.json"), manifest)
		desc, _ := json.Marshal(variantDescriptor{Edition: edition, AndroidAPI: 26, RuntimeManifestSHA: hashBytes(manifest), SourceCommit: source, DevtoolCommit: devtool})
		mustWrite(filepath.Join(expanded, "config/chrootctl/build-variant.json"), desc)
		for _, name := range append([]string{"runtime-manifest.json"}, func() []string {
			out := []string{}
			for _, f := range files {
				out = append(out, f.Path)
			}
			return out
		}()...) {
			b, e := os.ReadFile(filepath.Join(rt, name))
			if e != nil {
				t.Fatal(e)
			}
			mustWrite(filepath.Join(expanded, "runtime/arm64-v8a", name), b)
		}
		zpath := filepath.Join(root, "chrootctl-"+edition+"-arm64.zip")
		zfile, e := os.Create(zpath)
		if e != nil {
			t.Fatal(e)
		}
		w := zip.NewWriter(zfile)
		rels := []string{"config/chrootctl/build-variant.json", "runtime/arm64-v8a/runtime-manifest.json", "runtime/arm64-v8a/chrootctl"}
		if edition == "rclone" {
			rels = append(rels, "runtime/arm64-v8a/rclone")
		}
		for _, rel := range rels {
			b, e := os.ReadFile(filepath.Join(expanded, rel))
			if e != nil {
				t.Fatal(e)
			}
			member, e := w.Create(rel)
			if e != nil {
				t.Fatal(e)
			}
			if _, e = member.Write(b); e != nil {
				t.Fatal(e)
			}
		}
		if e = w.Close(); e != nil {
			t.Fatal(e)
		}
		if e = zfile.Close(); e != nil {
			t.Fatal(e)
		}
		sha, e := hash(zpath)
		if e != nil {
			t.Fatal(e)
		}
		mustWrite(zpath+".sha256", []byte(fmt.Sprintf("%s  %s\n", sha, filepath.Base(zpath))))
	}
	base := filepath.Join(root, "base/arm64-v8a")
	if e := os.MkdirAll(base, 0755); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(filepath.Join(base, "chrootctl"), content, 0755); e != nil {
		t.Fatal(e)
	}
	return root, source, devtool
}
func TestHostedDualReleasePositive(t *testing.T) {
	root, source, devtool := materializeDual(t)
	if err := run(root, source, devtool, filepath.Join(t.TempDir(), "publish")); err != nil {
		t.Fatal(err)
	}
}
func TestHostedDualReleaseRejectsCorruption(t *testing.T) {
	tests := []struct {
		name    string
		breakIt func(t *testing.T, root string)
	}{
		{"missing-rclone", func(t *testing.T, root string) {
			t.Helper()
			os.Remove(filepath.Join(root, "runtime/rclone/arm64-v8a/rclone"))
		}},
		{"standard-leaks-rclone", func(t *testing.T, root string) {
			t.Helper()
			p := filepath.Join(root, "runtime/standard/arm64-v8a/rclone")
			os.WriteFile(p, []byte("untracked executable"), 0755)
		}},
		{"wrong-source", func(t *testing.T, root string) {
			t.Helper()
			p := filepath.Join(root, "module/rclone/config/chrootctl/build-variant.json")
			b, e := os.ReadFile(p)
			if e != nil {
				t.Fatal(e)
			}
			os.WriteFile(p, []byte(strings.ReplaceAll(string(b), strings.Repeat("a", 40), strings.Repeat("f", 40))), 0644)
		}},
		{"sha-sidecar", func(t *testing.T, root string) {
			t.Helper()
			p := filepath.Join(root, "chrootctl-standard-arm64.zip.sha256")
			os.WriteFile(p, []byte("invalid"), 0644)
		}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			root, source, devtool := materializeDual(t)
			tt.breakIt(t, root)
			if err := run(root, source, devtool, ""); err == nil {
				t.Fatal("mutated release accepted")
			}
		})
	}
}
