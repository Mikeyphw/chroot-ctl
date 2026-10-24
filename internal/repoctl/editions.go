package repoctl

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	chmodule "chrootctl/internal/module"
)

const (
	EditionStandard   = "standard"
	EditionRclone     = "rclone"
	EditionAndroidAPI = 26
)

type DualEditionOptions struct {
	OutputRoot string
	RclonePath string
	Jobs       int
	CC         string
}

func validateEditionOption(edition string) error {
	if edition != "" && edition != EditionStandard && edition != EditionRclone {
		return fmt.Errorf("unknown Chrootctl edition %q (expected standard or rclone)", edition)
	}
	return nil
}
func editionAndroidAPI(edition string) int {
	if edition == "" {
		return 0
	}
	return EditionAndroidAPI
}
func explicitRcloneSource() (string, error) {
	return verifyRcloneSource(strings.TrimSpace(os.Getenv("CHROOTCTL_RCLONE_PATH")))
}
func verifyRcloneSource(path string) (string, error) {
	if path == "" {
		return "", errors.New("rclone edition requires a pinned, explicit --rclone or CHROOTCTL_RCLONE_PATH executable")
	}
	if !filepath.IsAbs(path) {
		return "", errors.New("rclone source must be an absolute path")
	}
	st, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if !st.Mode().IsRegular() || st.Mode()&os.ModeSymlink != 0 || st.Mode().Perm()&0111 == 0 {
		return "", errors.New("rclone source must be an executable regular file without symlinks")
	}
	if !isRcloneAndroidArm64Runtime(path) {
		return "", errors.New("rclone source is not Go/CGO Android ARM64 github.com/rclone/rclone executable")
	}
	if err := verifyRuntimePageSize(path); err != nil {
		return "", err
	}
	if err := verifyRcloneSourceReceipt(path); err != nil {
		return "", err
	}
	return path, nil
}

// The source-built rclone installer emits a locked, digest-bound receipt beside
// its binary; neither the user PATH nor a mutable download is release authority.
func verifyRcloneSourceReceipt(path string) error {
	raw, err := os.ReadFile(filepath.Join(filepath.Dir(path), "rclone-build-receipt.json"))
	if err != nil {
		return fmt.Errorf("required pinned rclone build receipt: %w", err)
	}
	var receipt struct {
		SchemaVersion int    `json:"schemaVersion"`
		SourceCommit  string `json:"sourceCommit"`
		AndroidAPI    int    `json:"androidApi"`
		PageSize      int    `json:"pageSize"`
		SHA256        string `json:"sha256"`
	}
	if err := json.Unmarshal(raw, &receipt); err != nil {
		return err
	}
	if receipt.SchemaVersion != 1 || receipt.AndroidAPI != 26 || receipt.PageSize != 16384 || len(receipt.SourceCommit) != 40 || len(receipt.SHA256) != 64 {
		return errors.New("rclone build receipt does not meet pinned API 26 identity")
	}
	root, rootErr := repoRoot()
	if rootErr != nil {
		return rootErr
	}
	lock, err := os.ReadFile(filepath.Join(root, "config/chrootctl/bclone-android-source.lock"))
	if err != nil {
		return err
	}
	if !strings.Contains(string(lock), "commit="+receipt.SourceCommit+"\n") || !strings.Contains(string(lock), "android_api=26\n") {
		return errors.New("rclone receipt source revision differs from lock")
	}
	sha, err := shaFile(path)
	if err != nil {
		return err
	}
	if sha != receipt.SHA256 {
		return errors.New("rclone receipt executable SHA-256 mismatch")
	}
	return nil
}
func verifyRuntimePageSize(path string) error {
	// Use the repository's native ELF verifier, avoiding self-declared manifest
	// claims. A pure Go ELF parser is used below to keep offline tests runnable.
	return verifyELFLoadAlignment(path, 16384)
}
func appendRcloneToRuntime(dir, source string, files *[]runtimeFile) error {
	if err := copyRuntimeFile(source, filepath.Join(dir, "rclone"), 0755); err != nil {
		return err
	}
	stat, err := os.Stat(filepath.Join(dir, "rclone"))
	if err != nil {
		return err
	}
	hash, err := shaFile(filepath.Join(dir, "rclone"))
	if err != nil {
		return err
	}
	*files = append(*files, runtimeFile{Path: "rclone", Size: stat.Size(), SHA256: hash, Executable: true})
	return nil
}
func requireRuntimeEdition(dir, edition string) error {
	if edition != EditionStandard && edition != EditionRclone {
		return errors.New("module edition must be standard or rclone")
	}
	raw, err := os.ReadFile(filepath.Join(dir, "runtime-manifest.json"))
	if err != nil {
		return err
	}
	var manifest runtimeManifest
	if err := json.Unmarshal(raw, &manifest); err != nil {
		return err
	}
	if manifest.Edition != edition || manifest.AndroidAPI != 26 {
		return errors.New("module edition differs from source runtime edition/API")
	}
	return nil
}

// AssembleEditionRuntime copies only files enumerated in a validated base
// manifest; stale binaries in out/, PATH or external directories cannot leak.
func AssembleEditionRuntime(baseDir, destRoot, edition, rclonePath string) (string, error) {
	if edition != EditionStandard && edition != EditionRclone {
		return "", errors.New("edition must be explicitly standard or rclone")
	}
	if err := chmodule.ValidateRuntime(baseDir); err != nil {
		return "", err
	}
	raw, err := os.ReadFile(filepath.Join(baseDir, "runtime-manifest.json"))
	if err != nil {
		return "", err
	}
	var base runtimeManifest
	if err := json.Unmarshal(raw, &base); err != nil {
		return "", err
	}
	for _, f := range base.Files {
		if f.Path == "rclone" {
			return "", errors.New("base runtime must never contain rclone")
		}
	}
	if edition == EditionRclone {
		if _, err = verifyRcloneSource(rclonePath); err != nil {
			return "", err
		}
	}
	if err := os.MkdirAll(destRoot, 0755); err != nil {
		return "", err
	}
	tmp, err := os.MkdirTemp(destRoot, ".edition-")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(tmp)
	base.Edition = edition
	base.AndroidAPI = EditionAndroidAPI
	for _, file := range base.Files {
		if file.Path == "runtime-manifest.json" || filepath.Base(file.Path) != file.Path {
			return "", errors.New("unexpected nested base runtime path")
		}
		mode := os.FileMode(0644)
		if file.Executable {
			mode = 0755
		}
		if err := copyRuntimeFile(filepath.Join(baseDir, file.Path), filepath.Join(tmp, file.Path), mode); err != nil {
			return "", err
		}
	}
	if edition == EditionRclone {
		if err := appendRcloneToRuntime(tmp, rclonePath, &base.Files); err != nil {
			return "", err
		}
	}
	payload, err := json.MarshalIndent(base, "", "  ")
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(filepath.Join(tmp, "runtime-manifest.json"), append(payload, '\n'), 0644); err != nil {
		return "", err
	}
	if err := chmodule.ValidateRuntime(tmp); err != nil {
		return "", err
	}
	dest := filepath.Join(destRoot, chmodule.RuntimeABI)
	if err := replaceDir(tmp, dest); err != nil {
		return "", err
	}
	return dest, nil
}

// BuildEditions is the release-only entrypoint. A single base native build is
// shared across two isolated module package trees, with no fallback to PATH.
func BuildEditions(opts DualEditionOptions) error {
	if strings.TrimSpace(os.Getenv("CHROOTCTL_TMUX_PATH")) == "" {
		return errors.New("dual release requires an explicit verified static tmux runtime")
	}
	if _, err := verifyRcloneSource(opts.RclonePath); err != nil {
		return err
	}
	root, err := repoRoot()
	if err != nil {
		return err
	}
	out := absFromRoot(root, opts.OutputRoot, "out/dual-release")
	if err := os.MkdirAll(filepath.Dir(out), 0755); err != nil {
		return err
	}
	// Assemble and verify both editions before atomically publishing the pair.
	staging, err := os.MkdirTemp(filepath.Dir(out), ".dual-editions-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(staging)
	base, err := BuildRuntime(RuntimeOptions{OutputRoot: filepath.Join(staging, "base"), Jobs: opts.Jobs, CC: opts.CC, Edition: EditionStandard})
	if err != nil {
		return err
	}
	// Both editions use identical chrootctl/tmux bytes from base.
	for _, edition := range []string{EditionStandard, EditionRclone} {
		runtime, err := AssembleEditionRuntime(base, filepath.Join(staging, "runtime", edition), edition, opts.RclonePath)
		if err != nil {
			return fmt.Errorf("assemble %s: %w", edition, err)
		}
		path := filepath.Join(staging, "chrootctl-"+edition+"-arm64.zip")
		if _, err := BuildModule(ModuleOptions{OutputDir: filepath.Join(staging, "module", edition), ZipPath: path, RuntimeDir: runtime, Edition: edition, Checksum: true}); err != nil {
			return fmt.Errorf("build %s: %w", edition, err)
		}
	}
	// An independent checksum of the shared native backend must match both editions.
	baseSHA, err := shaFile(filepath.Join(base, chmodule.RuntimeEntrypoint))
	if err != nil {
		return err
	}
	for _, edition := range []string{EditionStandard, EditionRclone} {
		sha, e := shaFile(filepath.Join(staging, "runtime", edition, chmodule.RuntimeABI, chmodule.RuntimeEntrypoint))
		if e != nil {
			return e
		}
		if sha != baseSHA {
			return errors.New("editions diverge from shared base runtime")
		}
	}
	return replaceDir(staging, out)
}
