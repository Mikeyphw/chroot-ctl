//go:build ignore

// Independent zip/edition/source verifier. Only Go standard library.
package main

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

type fileEntry struct {
	Path       string `json:"path"`
	Size       int64  `json:"size"`
	SHA256     string `json:"sha256"`
	Executable bool   `json:"executable"`
}
type runtimeManifest struct {
	Edition    string      `json:"edition"`
	AndroidAPI int         `json:"androidApi"`
	Files      []fileEntry `json:"files"`
}
type variantDescriptor struct {
	Edition            string `json:"edition"`
	AndroidAPI         int    `json:"androidApi"`
	RuntimeManifestSHA string `json:"runtimeManifestSha256"`
	SourceCommit       string `json:"sourceCommit"`
	DevtoolCommit      string `json:"devtoolCommit"`
}
type artifact struct {
	Edition            string `json:"edition"`
	Filename           string `json:"filename"`
	SHA256             string `json:"sha256"`
	Size               int64  `json:"size"`
	RuntimeManifestSHA string `json:"runtimeManifestSha256"`
}
type evidence struct {
	SchemaVersion      int        `json:"schemaVersion"`
	AndroidAPI         int        `json:"androidApi"`
	SourceCommit       string     `json:"sourceCommit"`
	DevtoolCommit      string     `json:"devtoolCommit"`
	SharedChrootctlSHA string     `json:"sharedChrootctlSHA256"`
	Artifacts          []artifact `json:"artifacts"`
	Qualification      string     `json:"qualification"`
}

func check(ok bool, msg string) error {
	if !ok {
		return errors.New(msg)
	}
	return nil
}
func hash(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
func hashBytes(p []byte) string             { h := sha256.Sum256(p); return hex.EncodeToString(h[:]) }
func fileBytes(path string) ([]byte, error) { return os.ReadFile(path) }
func readJSON(path string, v any) error {
	p, e := os.ReadFile(path)
	if e != nil {
		return e
	}
	return json.Unmarshal(p, v)
}
func run(root, source, devtool, publish string) error {
	var err error
	shaRE := regexp.MustCompile(`^[a-f0-9]{40}$`)
	if err := check(shaRE.MatchString(source) && shaRE.MatchString(devtool), "source/Devtool SHA is not full Git commit hash"); err != nil {
		return err
	}
	ev := evidence{SchemaVersion: 1, AndroidAPI: 26, SourceCommit: source, DevtoolCommit: devtool, Qualification: "HOSTED_CANDIDATE_NOT_DEVICE_QUALIFIED"}
	common := []string{}
	for _, edition := range []string{"standard", "rclone"} {
		name := "chrootctl-" + edition + "-arm64.zip"
		zpath := filepath.Join(root, name)
		runtime := filepath.Join(root, "runtime", edition, "arm64-v8a")
		expanded := filepath.Join(root, "module", edition)
		zipSHA, e := hash(zpath)
		if e != nil {
			return e
		}
		sidecar, e := fileBytes(zpath + ".sha256")
		if e != nil {
			return e
		}
		if err = check(strings.TrimSpace(string(sidecar)) == zipSHA+"  "+name, edition+": ZIP checksum differs"); err != nil {
			return err
		}
		var manifest runtimeManifest
		if e = readJSON(filepath.Join(runtime, "runtime-manifest.json"), &manifest); e != nil {
			return e
		}
		if err = check(manifest.Edition == edition && manifest.AndroidAPI == 26, edition+": runtime API/edition invalid"); err != nil {
			return err
		}
		names := make(map[string]bool)
		for _, entry := range manifest.Files {
			if err = check(entry.Path != "" && filepath.Base(entry.Path) == entry.Path && !names[entry.Path], edition+": invalid or repeated runtime path"); err != nil {
				return err
			}
			names[entry.Path] = true
			path := filepath.Join(runtime, entry.Path)
			st, e := os.Lstat(path)
			if e != nil {
				return e
			}
			if err = check(st.Mode().IsRegular() && st.Size() == entry.Size && (st.Mode().Perm()&0111 != 0) == entry.Executable, edition+": runtime mode/size differs: "+entry.Path); err != nil {
				return err
			}
			sha, e := hash(path)
			if e != nil {
				return e
			}
			if err = check(sha == entry.SHA256, edition+": runtime content differs: "+entry.Path); err != nil {
				return err
			}
		}
		if err = check(names["rclone"] == (edition == "rclone"), edition+": manifest rclone membership differs"); err != nil {
			return err
		}
		if _, stErr := os.Lstat(filepath.Join(runtime, "rclone")); stErr == nil && edition == "standard" {
			return fmt.Errorf("%s: unexpected unsealed rclone executable", edition)
		} else if stErr != nil && !os.IsNotExist(stErr) {
			return stErr
		}

		manifestSHA, e := hash(filepath.Join(runtime, "runtime-manifest.json"))
		if e != nil {
			return e
		}
		var variant variantDescriptor
		if e = readJSON(filepath.Join(expanded, "config/chrootctl/build-variant.json"), &variant); e != nil {
			return e
		}
		if err = check(variant.Edition == edition && variant.AndroidAPI == 26 && variant.RuntimeManifestSHA == manifestSHA && variant.SourceCommit == source && variant.DevtoolCommit == devtool, edition+": package variant/source seal differs"); err != nil {
			return err
		}
		archive, e := zip.OpenReader(zpath)
		if e != nil {
			return e
		}
		entries := make(map[string]*zip.File)
		for _, entry := range archive.File {
			key := entry.Name
			if key == "" || strings.HasPrefix(key, "/") || strings.Contains("/"+key+"/", "/../") || entries[key] != nil {
				archive.Close()
				return fmt.Errorf("%s: unsafe or duplicate ZIP entry: %s", edition, key)
			}
			entries[key] = entry
		}
		if err = check((entries["runtime/arm64-v8a/rclone"] != nil) == (edition == "rclone"), edition+": ZIP rclone membership differs"); err != nil {
			archive.Close()
			return err
		}
		for _, rel := range []string{"runtime/arm64-v8a/chrootctl", "runtime/arm64-v8a/runtime-manifest.json", "config/chrootctl/build-variant.json"} {
			f := entries[rel]
			if f == nil {
				archive.Close()
				return fmt.Errorf("%s: ZIP missing %s", edition, rel)
			}
			v, e := f.Open()
			if e != nil {
				archive.Close()
				return e
			}
			b, e := io.ReadAll(v)
			v.Close()
			if e != nil {
				archive.Close()
				return e
			}
			sha, e := hash(filepath.Join(expanded, filepath.FromSlash(rel)))
			if e != nil {
				archive.Close()
				return e
			}
			if err = check(hashBytes(b) == sha, edition+": ZIP/expanded tree differs for "+rel); err != nil {
				archive.Close()
				return err
			}
		}
		for rel := range names {
			key := "runtime/arm64-v8a/" + rel
			f := entries[key]
			if f == nil {
				archive.Close()
				return fmt.Errorf("%s: ZIP missing %s", edition, key)
			}
			v, e := f.Open()
			if e != nil {
				archive.Close()
				return e
			}
			b, e := io.ReadAll(v)
			v.Close()
			if e != nil {
				archive.Close()
				return e
			}
			sha, e := hash(filepath.Join(runtime, rel))
			if e != nil {
				archive.Close()
				return e
			}
			if err = check(hashBytes(b) == sha, edition+": ZIP/runtime differs for "+key); err != nil {
				archive.Close()
				return err
			}
		}
		archive.Close()
		shared, e := hash(filepath.Join(runtime, "chrootctl"))
		if e != nil {
			return e
		}
		common = append(common, shared)
		st, e := os.Stat(zpath)
		if e != nil {
			return e
		}
		ev.Artifacts = append(ev.Artifacts, artifact{Edition: edition, Filename: name, SHA256: zipSHA, Size: st.Size(), RuntimeManifestSHA: manifestSHA})
	}
	base, e := hash(filepath.Join(root, "base/arm64-v8a/chrootctl"))
	if e != nil {
		return e
	}
	if err := check(common[0] == common[1] && common[0] == base, "base and edition backends diverge"); err != nil {
		return err
	}
	if err := check(ev.Artifacts[0].SHA256 != ev.Artifacts[1].SHA256, "edition packages have identical bytes"); err != nil {
		return err
	}
	ev.SharedChrootctlSHA = base
	if publish != "" {
		if st, er := os.Lstat(publish); er == nil && (!st.IsDir() || st.Mode()&os.ModeSymlink != 0) {
			return errors.New("unsafe publication destination")
		}
		if e = os.MkdirAll(publish, 0755); e != nil {
			return e
		}
		for _, a := range ev.Artifacts {
			for _, name := range []string{a.Filename, a.Filename + ".sha256"} {
				p, e := fileBytes(filepath.Join(root, name))
				if e != nil {
					return e
				}
				if e = os.WriteFile(filepath.Join(publish, name), p, 0644); e != nil {
					return e
				}
			}
		}
		p, e := json.MarshalIndent(ev, "", "  ")
		if e != nil {
			return e
		}
		if e = os.WriteFile(filepath.Join(publish, "release-evidence.json"), append(p, '\n'), 0644); e != nil {
			return e
		}
		var sums strings.Builder
		for _, a := range ev.Artifacts {
			fmt.Fprintf(&sums, "%s  %s\n", a.SHA256, a.Filename)
		}
		if e = os.WriteFile(filepath.Join(publish, "SHA256SUMS"), []byte(sums.String()), 0644); e != nil {
			return e
		}
	}
	fmt.Println("PASS_DUAL_API26_STANDALONE_ZIP_RUNTIME_PROVENANCE_VERIFICATION")
	b, e := json.Marshal(ev)
	if e != nil {
		return e
	}
	fmt.Println(string(b))
	return nil
}
func main() {
	root := flag.String("root", "", "dual-release dir")
	source := flag.String("source", "", "source commit")
	devtool := flag.String("devtool", "", "Devtool commit")
	publish := flag.String("publish", "", "publish destination")
	flag.Parse()
	if *root == "" {
		fmt.Fprintln(os.Stderr, "--root required")
		os.Exit(2)
	}
	if err := run(*root, *source, *devtool, *publish); err != nil {
		fmt.Fprintln(os.Stderr, "FAIL_DUAL_RELEASE:", err)
		os.Exit(1)
	}
}
