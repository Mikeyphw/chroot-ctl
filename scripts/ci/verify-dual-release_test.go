//go:build ignore

package main

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"io"
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
		mustWrite(filepath.Join(expanded, "webroot/index.html"), []byte("VALIDATED-WEBUI-FIXTURE"))
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
			if name == "chrootctl" || name == "rclone" {
				if e := os.Chmod(filepath.Join(expanded, "runtime/arm64-v8a", name), 0755); e != nil {
					t.Fatal(e)
				}
			}
		}
		zpath := filepath.Join(root, "chrootctl-"+edition+"-arm64.zip")
		zfile, e := os.Create(zpath)
		if e != nil {
			t.Fatal(e)
		}
		w := zip.NewWriter(zfile)
		rels := []string{"config/chrootctl/build-variant.json", "runtime/arm64-v8a/runtime-manifest.json", "runtime/arm64-v8a/chrootctl", "webroot/index.html"}
		if edition == "rclone" {
			rels = append(rels, "runtime/arm64-v8a/rclone")
		}
		for _, rel := range rels {
			b, e := os.ReadFile(filepath.Join(expanded, rel))
			if e != nil {
				t.Fatal(e)
			}
			info, e := os.Stat(filepath.Join(expanded, rel))
			if e != nil {
				t.Fatal(e)
			}
			hdr := &zip.FileHeader{Name: rel, Method: zip.Deflate}
			hdr.SetMode(info.Mode().Perm())
			member, e := w.CreateHeader(hdr)
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

// Regression: the previous independent verifier only checked a few selected
// archive files. An attacker/stale producer could alter any other ZIP member,
// recompute the sidecar and still obtain a purported verification PASS.
func TestCC12RejectsUnsealedZipOrStagedMembers(t *testing.T) {
	for _, mutation := range []string{"extra-zip-file", "tamper-webui", "omit-webui", "extra-staged-file", "mode-mismatch"} {
		t.Run(mutation, func(t *testing.T) {
			root, source, devtool := materializeDual(t)
			edition := "standard"
			zipPath := filepath.Join(root, "chrootctl-"+edition+"-arm64.zip")
			orig, err := zip.OpenReader(zipPath)
			if err != nil {
				t.Fatal(err)
			}
			tmp := zipPath + ".new"
			out, err := os.Create(tmp)
			if err != nil {
				t.Fatal(err)
			}
			zw := zip.NewWriter(out)
			for _, f := range orig.File {
				if mutation == "omit-webui" && f.Name == "webroot/index.html" {
					continue
				}
				h := f.FileHeader
				if mutation == "mode-mismatch" && f.Name == "runtime/arm64-v8a/chrootctl" {
					h.SetMode(0644)
				}
				dst, err := zw.CreateHeader(&h)
				if err != nil {
					t.Fatal(err)
				}
				input, err := f.Open()
				if err != nil {
					t.Fatal(err)
				}
				_, err = io.Copy(dst, input)
				input.Close()
				if err != nil {
					t.Fatal(err)
				}
				if mutation == "tamper-webui" && f.Name == "webroot/index.html" {
					if _, err := dst.Write([]byte("CORRUPTED")); err != nil {
						t.Fatal(err)
					}
				}
			}
			if mutation == "extra-zip-file" {
				extra, err := zw.Create("unsealed-extra.txt")
				if err != nil {
					t.Fatal(err)
				}
				extra.Write([]byte("unlisted"))
			}
			if err := zw.Close(); err != nil {
				t.Fatal(err)
			}
			if err := out.Close(); err != nil {
				t.Fatal(err)
			}
			orig.Close()
			if err := os.Rename(tmp, zipPath); err != nil {
				t.Fatal(err)
			}
			sum, err := hash(zipPath)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(zipPath+".sha256", []byte(sum+"  "+filepath.Base(zipPath)+"\n"), 0644); err != nil {
				t.Fatal(err)
			}
			if mutation == "extra-staged-file" {
				p := filepath.Join(root, "module", edition, "webroot/extra.html")
				if err := os.WriteFile(p, []byte("unsealed staging"), 0644); err != nil {
					t.Fatal(err)
				}
			}
			if err := run(root, source, devtool, ""); err == nil {
				t.Fatal("tampered release was accepted")
			}
		})
	}
}
