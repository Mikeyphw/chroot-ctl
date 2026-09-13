package repoctl

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	"chrootctl/internal/contractgen"
	"chrootctl/internal/contracts"
	chmodule "chrootctl/internal/module"
	chsystem "chrootctl/internal/system"

	"chrootctl/internal/testseal"
)

const defaultNDKVersion = "29.0.14206865"
const defaultAndroidAPI = 26

type RuntimeOptions struct {
	OutputRoot string
	Jobs       int
	CC         string
}
type ModuleOptions struct {
	OutputDir, ZipPath, RuntimeDir string
	StartupTargets                 []string
	Jobs                           int
	Install, Checksum              bool
}
type SourceOptions struct {
	Version, Output string
	Checksum        bool
}
type ReleaseOptions struct {
	Version, DistDir string
	Jobs             int
	GO02Evidence     string
}

type runtimeFile struct {
	Path       string `json:"path"`
	Size       int64  `json:"size"`
	SHA256     string `json:"sha256"`
	Executable bool   `json:"executable"`
}
type runtimeManifest struct {
	SchemaVersion         int           `json:"schemaVersion"`
	RuntimeKind           string        `json:"runtimeKind"`
	Platform              string        `json:"platform"`
	ABI                   string        `json:"abi"`
	Entrypoint            string        `json:"entrypoint"`
	BackendVersion        string        `json:"backendVersion"`
	BridgeProtocolVersion int           `json:"bridgeProtocolVersion"`
	Files                 []runtimeFile `json:"files"`
}

func repoRoot() (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for cur := cwd; ; cur = filepath.Dir(cur) {
		if _, e := os.Stat(filepath.Join(cur, "go.mod")); e == nil {
			return cur, nil
		}
		next := filepath.Dir(cur)
		if next == cur {
			break
		}
	}
	return "", errors.New("repoctl must run inside the chrootctl repository")
}
func absFromRoot(root, value, fallback string) string {
	if value == "" {
		value = fallback
	}
	if !filepath.IsAbs(value) {
		value = filepath.Join(root, value)
	}
	out, _ := filepath.Abs(value)
	return out
}
func safeDir(path string) error {
	st, e := os.Lstat(path)
	if e != nil {
		return e
	}
	if st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
		return fmt.Errorf("unsafe directory: %s", path)
	}
	return nil
}
func replaceDir(tmp, dst string) error {
	if st, e := os.Lstat(dst); e == nil {
		if st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
			return fmt.Errorf("refusing unsafe output directory: %s", dst)
		}
		if e = os.RemoveAll(dst); e != nil {
			return e
		}
	} else if !os.IsNotExist(e) {
		return e
	}
	return os.Rename(tmp, dst)
}
func shaFile(path string) (string, error) {
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
func WriteChecksum(path string) (string, error) {
	sum, e := shaFile(path)
	if e != nil {
		return "", e
	}
	out := path + ".sha256"
	return out, os.WriteFile(out, []byte(fmt.Sprintf("%s  %s\n", sum, filepath.Base(path))), 0644)
}

func resolveAndroidCC(explicit string) (string, error) {
	if explicit == "" {
		explicit = os.Getenv("CHROOTCTL_ANDROID_CC")
	}
	if explicit != "" {
		if !filepath.IsAbs(explicit) {
			return "", errors.New("CHROOTCTL_ANDROID_CC must be absolute")
		}
		if st, e := os.Stat(explicit); e != nil || st.Mode()&0111 == 0 {
			return "", fmt.Errorf("compiler is not executable: %s", explicit)
		}
		return explicit, nil
	}
	prefixes := []string{os.Getenv("PREFIX"), "/data/data/com.termux/files/usr"}
	for _, pre := range prefixes {
		if pre == "" {
			continue
		}
		c := filepath.Join(pre, "bin/clang")
		if st, e := os.Stat(c); e == nil && st.Mode()&0111 != 0 {
			return c, nil
		}
	}
	api := defaultAndroidAPI
	if v := os.Getenv("CHROOTCTL_ANDROID_API"); v != "" {
		if n, e := strconv.Atoi(v); e == nil {
			api = n
		}
	}
	ndkVer := os.Getenv("CHROOTCTL_ANDROID_NDK_VERSION")
	if ndkVer == "" {
		ndkVer = defaultNDKVersion
	}
	roots := []string{os.Getenv("ANDROID_NDK_ROOT"), os.Getenv("ANDROID_NDK_HOME")}
	for _, sdk := range []string{os.Getenv("ANDROID_SDK_ROOT"), os.Getenv("ANDROID_HOME")} {
		if sdk != "" {
			roots = append(roots, filepath.Join(sdk, "ndk", ndkVer))
		}
	}
	needle := fmt.Sprintf("aarch64-linux-android%d-clang", api)
	for _, root := range roots {
		if root == "" {
			continue
		}
		pre := filepath.Join(root, "toolchains/llvm/prebuilt")
		entries, _ := os.ReadDir(pre)
		for _, ent := range entries {
			c := filepath.Join(pre, ent.Name(), "bin", needle)
			if st, e := os.Stat(c); e == nil && st.Mode()&0111 != 0 {
				return c, nil
			}
		}
	}
	return "", fmt.Errorf("no Android arm64 C compiler found; set CHROOTCTL_ANDROID_CC or install NDK %s", ndkVer)
}
func run(root string, env []string, args ...string) error {
	cmd := exec.Command(args[0], args[1:]...)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), env...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	return cmd.Run()
}

func BuildRuntime(opts RuntimeOptions) (string, error) {
	root, e := repoRoot()
	if e != nil {
		return "", e
	}
	if opts.Jobs <= 0 {
		opts.Jobs = 2
	}
	outRoot := absFromRoot(root, opts.OutputRoot, "out/native-runtime")
	final := filepath.Join(outRoot, chmodule.RuntimeABI)
	if e = os.MkdirAll(outRoot, 0755); e != nil {
		return "", e
	}
	tmp, e := os.MkdirTemp(outRoot, ".arm64-v8a-")
	if e != nil {
		return "", e
	}
	defer os.RemoveAll(tmp)
	cc, e := resolveAndroidCC(opts.CC)
	if e != nil {
		return "", e
	}
	binary := filepath.Join(tmp, chmodule.RuntimeEntrypoint)
	fmt.Fprintf(os.Stderr, "repoctl: Android compiler: %s\n", cc)
	env := []string{"GOOS=android", "GOARCH=arm64", "CGO_ENABLED=1", "CC=" + cc, "GOMAXPROCS=" + strconv.Itoa(opts.Jobs)}
	if e = run(root, env, "go", "build", "-trimpath", "-tags", "android", "-p", strconv.Itoa(opts.Jobs), "-o", binary, "./cmd/chrootctl"); e != nil {
		return "", e
	}
	if e = os.Chmod(binary, 0755); e != nil {
		return "", e
	}
	st, e := os.Stat(binary)
	if e != nil {
		return "", e
	}
	sum, e := shaFile(binary)
	if e != nil {
		return "", e
	}
	m := runtimeManifest{SchemaVersion: chmodule.RuntimeSchemaVersion, RuntimeKind: chmodule.RuntimeKind, Platform: "android", ABI: chmodule.RuntimeABI, Entrypoint: chmodule.RuntimeEntrypoint, BackendVersion: chmodule.BackendVersion, BridgeProtocolVersion: chmodule.BridgeProtocolVersion, Files: []runtimeFile{{Path: chmodule.RuntimeEntrypoint, Size: st.Size(), SHA256: sum, Executable: true}}}
	raw, _ := json.MarshalIndent(m, "", "  ")
	raw = append(raw, '\n')
	if e = os.WriteFile(filepath.Join(tmp, "runtime-manifest.json"), raw, 0644); e != nil {
		return "", e
	}
	if e = chmodule.ValidateRuntime(tmp); e != nil {
		return "", e
	}
	if e = replaceDir(tmp, final); e != nil {
		return "", e
	}
	return final, nil
}

func BuildModule(opts ModuleOptions) (string, error) {
	root, e := repoRoot()
	if e != nil {
		return "", e
	}
	out := absFromRoot(root, opts.OutputDir, "out/module")
	zipPath := absFromRoot(root, opts.ZipPath, "chrootctl-magisk.zip")
	runtimeDir := opts.RuntimeDir
	if runtimeDir == "" {
		runtimeDir, e = BuildRuntime(RuntimeOptions{Jobs: opts.Jobs})
		if e != nil {
			return "", e
		}
	} else {
		runtimeDir = absFromRoot(root, runtimeDir, runtimeDir)
	}
	if e = chmodule.ValidateRuntime(runtimeDir); e != nil {
		return "", e
	}
	parent := filepath.Dir(out)
	if e = os.MkdirAll(parent, 0755); e != nil {
		return "", e
	}
	tmp, e := os.MkdirTemp(parent, ".module-")
	if e != nil {
		return "", e
	}
	defer os.RemoveAll(tmp)
	if e = chmodule.Render(chmodule.Options{OutputDir: tmp, NativeRuntimeDir: runtimeDir, StartupTargets: opts.StartupTargets}); e != nil {
		return "", e
	}
	if e = replaceDir(tmp, out); e != nil {
		return "", e
	}
	if e = chmodule.ValidateRendered(out); e != nil {
		return "", e
	}
	if e = chmodule.Zip(out, zipPath); e != nil {
		return "", e
	}
	if opts.Checksum {
		if _, e = WriteChecksum(zipPath); e != nil {
			return "", e
		}
	}
	if opts.Install {
		if e = InstallModule(zipPath); e != nil {
			return "", e
		}
		if e = os.Remove(zipPath); e != nil {
			return "", e
		}
		_ = os.Remove(zipPath + ".sha256")
	}
	return zipPath, nil
}
func shellQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'" }

func installModuleShell(abs string) string {
	quoted := shellQuote(abs)
	return strings.Join([]string{
		"if command -v ksud >/dev/null 2>&1; then exec ksud module install " + quoted + "; fi",
		"if [ -x /data/adb/ksud ]; then exec /data/adb/ksud module install " + quoted + "; fi",
		"if command -v magisk >/dev/null 2>&1; then exec magisk --install-module " + quoted + "; fi",
		"echo 'no supported Magisk/KernelSU module installer found in root shell' >&2",
		"exit 127",
	}, "\n")
}

func InstallModule(zipPath string) error {
	abs, e := filepath.Abs(zipPath)
	if e != nil {
		return e
	}
	if _, e = os.Stat(abs); e != nil {
		return e
	}
	cmd := exec.Command("su", "-c", installModuleShell(abs))
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	return cmd.Run()
}

var excludedDirs = map[string]bool{".git": true, "dist": true, "out": true, ".devtool": true, "tmpout": true, ".gradle": true, ".kotlin": true, "build": true}
var excludedSourceFiles = map[string]bool{"local.properties": true}

func forbiddenName(name string) bool {
	return strings.HasSuffix(name, ".pyc") || strings.HasSuffix(name, ".orig") || strings.HasSuffix(name, ".rej") || strings.HasSuffix(name, "~") || strings.Contains(name, ".bak")
}
func BuildSource(opts SourceOptions) (string, error) {
	root, e := repoRoot()
	if e != nil {
		return "", e
	}
	if opts.Version == "" {
		opts.Version = "dev"
	}
	out := opts.Output
	if out == "" {
		out = filepath.Join("dist", "chrootctl-source-"+opts.Version+".tar.gz")
	}
	out = absFromRoot(root, out, out)
	if e = os.MkdirAll(filepath.Dir(out), 0755); e != nil {
		return "", e
	}
	var paths []string
	e = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if path == root {
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		parts := strings.Split(filepath.ToSlash(rel), "/")
		if excludedDirs[parts[0]] {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		for _, part := range parts {
			if excludedDirs[part] {
				if d.IsDir() {
					return filepath.SkipDir
				}
				return nil
			}
		}
		if d.IsDir() && (transientCacheDirs[d.Name()] || pythonPackagingResidueDir(d.Name())) {
			return filepath.SkipDir
		}
		if !d.IsDir() && excludedSourceFiles[d.Name()] {
			return nil
		}
		if !d.IsDir() && pythonBytecode(d.Name()) {
			return nil
		}
		if forbiddenName(d.Name()) {
			return fmt.Errorf("forbidden source artifact: %s", rel)
		}
		if path == out {
			return nil
		}
		paths = append(paths, rel)
		return nil
	})
	if e != nil {
		return "", e
	}
	sort.Strings(paths)
	tmp := out + ".tmp"
	f, e := os.Create(tmp)
	if e != nil {
		return "", e
	}
	gz := gzip.NewWriter(f)
	gz.Header.ModTime = time.Unix(0, 0)
	gz.Header.Name = ""
	tw := tar.NewWriter(gz)
	base := filepath.Base(root)
	epoch := time.Unix(0, 0)
	for _, rel := range paths {
		path := filepath.Join(root, rel)
		st, e := os.Lstat(path)
		if os.IsNotExist(e) {
			// Ignore a path which disappeared after WalkDir (for example a
			// concurrent cleanup of generated cache residue during validation).
			continue
		}
		if e != nil {
			tw.Close()
			gz.Close()
			f.Close()
			return "", e
		}
		link := ""
		if st.Mode()&os.ModeSymlink != 0 {
			link, e = os.Readlink(path)
			if e != nil {
				return "", e
			}
		}
		h, e := tar.FileInfoHeader(st, link)
		if e != nil {
			return "", e
		}
		h.Name = filepath.ToSlash(filepath.Join(base, rel))
		h.ModTime = epoch
		h.AccessTime = epoch
		h.ChangeTime = epoch
		h.Uid = 0
		h.Gid = 0
		h.Uname = ""
		h.Gname = ""
		if e = tw.WriteHeader(h); e != nil {
			return "", e
		}
		if st.Mode().IsRegular() {
			src, e := os.Open(path)
			if e != nil {
				return "", e
			}
			_, e = io.Copy(tw, src)
			src.Close()
			if e != nil {
				return "", e
			}
		}
	}
	if e = tw.Close(); e != nil {
		return "", e
	}
	if e = gz.Close(); e != nil {
		return "", e
	}
	if e = f.Close(); e != nil {
		return "", e
	}
	if e = os.Rename(tmp, out); e != nil {
		return "", e
	}
	if opts.Checksum {
		if _, e = WriteChecksum(out); e != nil {
			return "", e
		}
	}
	return out, nil
}

func Validate() error {
	root, e := repoRoot()
	if e != nil {
		return e
	}
	if e = testseal.Validate(root, false); e != nil {
		return e
	}
	if e = ValidateRepositoryPurity(root); e != nil {
		return e
	}
	if e = ValidateAuditCoverage(root); e != nil {
		return e
	}
	if e = ValidateBuildFoundation(root); e != nil {
		return e
	}
	if e = contractgen.Check(root); e != nil {
		return e
	}
	if e = ValidateCLIContractFoundation(root); e != nil {
		return e
	}
	if e = ValidateConfigRegistryFoundation(root); e != nil {
		return e
	}
	if e = ValidatePrivilegeTrustBoundary(root); e != nil {
		return e
	}
	if e = ValidateProcessTransportBoundary(root); e != nil {
		return e
	}
	if e = ValidateMutationEngineGateA(root); e != nil {
		return e
	}
	if e = ValidateCRUDAtomicity(root); e != nil {
		return e
	}
	if e = ValidateMountServiceRuntime(root); e != nil {
		return e
	}
	if e = ValidateSnapshotFidelity(root); e != nil {
		return e
	}
	if e = ValidateTransferArtifactPlane(root); e != nil {
		return e
	}
	if e = ValidateInstallerUpgradeReconstruction(root); e != nil {
		return e
	}
	bundle, e := contracts.LoadDir(filepath.Join(root, "migration", "contracts", "v1"))
	if e != nil {
		return e
	}
	if e = bundle.Validate(); e != nil {
		return e
	}
	if e = ValidateLiveContracts(root, bundle); e != nil {
		return e
	}
	if e = run(root, nil, "go", "test", "-p", "2", "./..."); e != nil {
		return e
	}
	return run(root, nil, "go", "vet", "./...")
}
func DoctorCrossArch(arches []string) error {
	if len(arches) == 0 {
		arches = []string{"arm64"}
	}
	payload := map[string]any{"host_arch": chsystem.HostArch()}
	var checks []map[string]any
	for _, a := range arches {
		checks = append(checks, map[string]any{"arch": a, "qemu_binfmt_ready": chsystem.CanExecuteForeignArch(a)})
	}
	payload["checks"] = checks
	raw, _ := json.MarshalIndent(payload, "", "  ")
	fmt.Println(string(raw))
	return nil
}
func Release(opts ReleaseOptions) error {
	if opts.Version == "" {
		opts.Version = "dev"
	}
	if opts.DistDir == "" {
		opts.DistDir = "dist"
	}
	root, _ := repoRoot()
	dist := absFromRoot(root, opts.DistDir, "dist")
	if e := os.MkdirAll(dist, 0755); e != nil {
		return e
	}
	if e := FinalSeal(FinalSealOptions{Jobs: opts.Jobs, GO02Evidence: opts.GO02Evidence, EvidencePath: filepath.Join(dist, "validation-results.json")}); e != nil {
		return e
	}
	runtime, e := BuildRuntime(RuntimeOptions{OutputRoot: filepath.Join(dist, "runtime-"+opts.Version), Jobs: opts.Jobs})
	if e != nil {
		return e
	}
	moduleDir := filepath.Join(dist, "magisk-"+opts.Version)
	zipPath := filepath.Join(dist, "chrootctl-magisk-"+opts.Version+".zip")
	if _, e = BuildModule(ModuleOptions{OutputDir: moduleDir, ZipPath: zipPath, RuntimeDir: runtime, Jobs: opts.Jobs, Checksum: true}); e != nil {
		return e
	}
	src, e := BuildSource(SourceOptions{Version: opts.Version, Output: filepath.Join(dist, "chrootctl-source-"+opts.Version+".tar.gz"), Checksum: true})
	if e != nil {
		return e
	}
	fmt.Printf("release-ready: %s %s\n", zipPath, src)
	return nil
}

func HostSummary() string {
	return fmt.Sprintf("%s/%s go=%s", runtime.GOOS, runtime.GOARCH, runtime.Version())
}
