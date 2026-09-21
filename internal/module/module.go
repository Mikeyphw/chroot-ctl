package module

import (
	"archive/zip"
	"crypto/sha256"
	"debug/elf"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"chrootctl/internal/validation"
)

const (
	ModuleID              = "chrootctl-magisk"
	ModuleName            = "chrootctl Magisk Module"
	ModuleVersion         = "1.3.3"
	ModuleVersionCode     = 18
	BackendVersion        = "0.11.0"
	BridgeProtocolVersion = 1
	RuntimeSchemaVersion  = 2
	RuntimeKind           = "go-native"
	RuntimeABI            = "arm64-v8a"
	RuntimeEntrypoint     = "chrootctl"

	ModulePackageSchemaVersion = 1
	ModulePackageManifestPath  = "config/chrootctl/module-package-manifest.json"
)

// webUIFS is compiled into repoctl so module rendering is deterministic and
// does not depend on the caller's working directory.
//
//go:embed webroot/*
var webUIFS embed.FS

var webUIAssetPaths = []string{
	"index.html",
	"index.css",
	"index.js",
	"kernelsu.js",
	"chrootctl.js",
}

func requiredModuleFiles() []string {
	required := []string{
		"module.prop", "customize.sh", "post-fs-data.sh", "service.sh", "uninstall.sh",
		"bin/chrootctl-magisk-helper", "bin/chrootctl-log-helper", "system/bin/chrootctl", "system/bin/chrootctl-magisk-helper",
		"config/chrootctl/compatibility-manifest.json", "config/chrootctl/boot_targets.json",
		"runtime/" + RuntimeABI + "/runtime-manifest.json",
		"runtime/" + RuntimeABI + "/" + RuntimeEntrypoint,
	}
	for _, asset := range webUIAssetPaths {
		required = append(required, "webroot/"+asset)
	}
	return required
}

type Options struct {
	OutputDir        string
	ZipPath          string
	NativeRuntimeDir string
	StartupTargets   []string
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

type modulePackageFile struct {
	Path       string `json:"path"`
	Size       int64  `json:"size"`
	SHA256     string `json:"sha256"`
	Mode       string `json:"mode"`
	Executable bool   `json:"executable"`
}

type modulePackageManifest struct {
	SchemaVersion         int                 `json:"schemaVersion"`
	ModuleID              string              `json:"moduleId"`
	ModuleName            string              `json:"moduleName"`
	ModuleVersion         string              `json:"moduleVersion"`
	ModuleVersionCode     int                 `json:"moduleVersionCode"`
	BackendVersion        string              `json:"backendVersion"`
	BridgeProtocolVersion int                 `json:"bridgeProtocolVersion"`
	RuntimeSchemaVersion  int                 `json:"runtimeSchemaVersion"`
	RuntimeKind           string              `json:"runtimeKind"`
	RuntimeABI            string              `json:"runtimeAbi"`
	RuntimeEntrypoint     string              `json:"runtimeEntrypoint"`
	StartupTargets        []string            `json:"startupTargets"`
	Files                 []modulePackageFile `json:"files"`
}

func CompatibilityPayload() map[string]any {
	return map[string]any{
		"schemaVersion":         3,
		"project":               "chrootctl",
		"bridgeProtocolVersion": BridgeProtocolVersion,
		"backend":               map[string]any{"implementation": "go", "version": BackendVersion},
		"nativeRuntime":         map[string]any{"schemaVersion": RuntimeSchemaVersion, "kind": RuntimeKind, "platform": "android", "abi": RuntimeABI, "entrypoint": RuntimeEntrypoint, "optionalExecutables": []string{"rclone"}},
		"androidApp":            map[string]any{"applicationId": "com.mikeyphw.chrootctl", "versionName": "0.1.0-phase29", "versionCode": 1, "minimumSupportedModuleVersionCode": ModuleVersionCode},
		"module":                map[string]any{"id": ModuleID, "version": ModuleVersion, "versionCode": ModuleVersionCode, "minimumSupportedBridgeProtocolVersion": BridgeProtocolVersion},
	}
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
func safeRegular(path string) (fs.FileInfo, error) {
	st, e := os.Lstat(path)
	if e != nil {
		return nil, e
	}
	if st.Mode()&os.ModeSymlink != 0 || !st.Mode().IsRegular() {
		return nil, fmt.Errorf("unsafe non-regular file: %s", path)
	}
	return st, nil
}

func ValidateRuntime(root string) error {
	st, e := os.Lstat(root)
	if e != nil {
		return e
	}
	if st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
		return fmt.Errorf("native runtime must be a real directory: %s", root)
	}
	raw, e := os.ReadFile(filepath.Join(root, "runtime-manifest.json"))
	if e != nil {
		return e
	}
	var m runtimeManifest
	if e = json.Unmarshal(raw, &m); e != nil {
		return e
	}
	if m.SchemaVersion != RuntimeSchemaVersion || m.RuntimeKind != RuntimeKind || m.Platform != "android" || m.ABI != RuntimeABI || m.Entrypoint != RuntimeEntrypoint || m.BackendVersion != BackendVersion || m.BridgeProtocolVersion != BridgeProtocolVersion {
		return errors.New("native runtime identity mismatch")
	}
	if len(m.Files) == 0 {
		return errors.New("native runtime file inventory is empty")
	}
	seen := map[string]bool{}
	for _, rf := range m.Files {
		clean := filepath.Clean(rf.Path)
		if clean == "." || filepath.IsAbs(clean) || strings.HasPrefix(clean, ".."+string(filepath.Separator)) || clean == "runtime-manifest.json" || seen[clean] {
			return fmt.Errorf("unsafe runtime inventory path: %s", rf.Path)
		}
		seen[clean] = true
		p := filepath.Join(root, clean)
		st, e := safeRegular(p)
		if e != nil {
			return e
		}
		if st.Size() != rf.Size {
			return fmt.Errorf("runtime size mismatch: %s", clean)
		}
		sum, e := shaFile(p)
		if e != nil {
			return e
		}
		if sum != rf.SHA256 {
			return fmt.Errorf("runtime checksum mismatch: %s", clean)
		}
		if (st.Mode().Perm()&0111 != 0) != rf.Executable {
			return fmt.Errorf("runtime executable mode mismatch: %s", clean)
		}
	}
	actual := map[string]bool{}
	e = filepath.WalkDir(root, func(p string, d fs.DirEntry, e error) error {
		if e != nil {
			return e
		}
		if p == root {
			return nil
		}
		rel, _ := filepath.Rel(root, p)
		if d.Type()&os.ModeSymlink != 0 {
			return fmt.Errorf("runtime symlink forbidden: %s", rel)
		}
		if d.IsDir() {
			return nil
		}
		if rel != "runtime-manifest.json" {
			actual[rel] = true
		}
		return nil
	})
	if e != nil {
		return e
	}
	if len(actual) != len(seen) {
		return errors.New("native runtime inventory mismatch")
	}
	for k := range actual {
		if !seen[k] {
			return fmt.Errorf("uninventoried runtime file: %s", k)
		}
	}
	ep := filepath.Join(root, RuntimeEntrypoint)
	st, e = safeRegular(ep)
	if e != nil {
		return e
	}
	if st.Mode().Perm()&0111 == 0 {
		return errors.New("native runtime entrypoint is not executable")
	}
	if err := validateAndroidArm64RuntimeELF(ep, "native runtime entrypoint"); err != nil {
		return err
	}
	if seen["rclone"] {
		if err := validateAndroidArm64RuntimeELF(filepath.Join(root, "rclone"), "bundled rclone runtime"); err != nil {
			return err
		}
	}
	return nil
}

func validateAndroidArm64RuntimeELF(path, label string) error {
	ef, err := elf.Open(path)
	if err != nil {
		return fmt.Errorf("%s is not a valid ELF: %w", label, err)
	}
	defer ef.Close()
	if ef.Class != elf.ELFCLASS64 || ef.Data != elf.ELFDATA2LSB || ef.Machine != elf.EM_AARCH64 || ef.Type != elf.ET_DYN {
		return fmt.Errorf("%s ELF identity mismatch: class=%s data=%s machine=%s type=%s", label, ef.Class, ef.Data, ef.Machine, ef.Type)
	}
	interpreter := ""
	for _, prog := range ef.Progs {
		if prog.Type != elf.PT_INTERP {
			continue
		}
		raw, readErr := io.ReadAll(io.LimitReader(prog.Open(), 256))
		if readErr != nil {
			return fmt.Errorf("read %s interpreter: %w", label, readErr)
		}
		interpreter = strings.TrimRight(string(raw), "\x00")
		break
	}
	if interpreter != "/system/bin/linker64" {
		return fmt.Errorf("%s Android interpreter mismatch: %q", label, interpreter)
	}
	if err := validateDynamicLibraries(ef); err != nil {
		return fmt.Errorf("%s: %w", label, err)
	}
	return nil
}

func validateDynamicLibraries(ef *elf.File) error {
	libs, err := ef.ImportedLibraries()
	if err != nil {
		return fmt.Errorf("read native runtime dynamic libraries: %w", err)
	}
	allowed := map[string]bool{
		"libandroid.so": true,
		"libc.so":       true,
		"libdl.so":      true,
		"liblog.so":     true,
		"libm.so":       true,
	}
	for _, lib := range libs {
		if strings.Contains(lib, "/") || !allowed[lib] {
			return fmt.Errorf("native runtime imports unsupported dynamic library: %s", lib)
		}
	}
	return nil
}

func writeFile(root, rel, content string, mode fs.FileMode) error {
	p := filepath.Join(root, filepath.FromSlash(rel))
	if e := os.MkdirAll(filepath.Dir(p), 0755); e != nil {
		return e
	}
	if err := os.WriteFile(p, []byte(content), mode); err != nil {
		return err
	}
	// os.WriteFile applies the process umask when creating a file. Module output
	// has an explicit mode contract, so normalize it after creation as well.
	return os.Chmod(p, mode)
}

func writeWebUI(root string) error {
	for _, asset := range webUIAssetPaths {
		raw, err := webUIFS.ReadFile("webroot/" + asset)
		if err != nil {
			return fmt.Errorf("read embedded WebUI asset %s: %w", asset, err)
		}
		if len(raw) == 0 {
			return fmt.Errorf("embedded WebUI asset is empty: %s", asset)
		}
		if err = writeFile(root, "webroot/"+asset, string(raw), 0644); err != nil {
			return fmt.Errorf("write WebUI asset %s: %w", asset, err)
		}
	}
	return nil
}

func ignoredLocalArtifact(rel string) bool {
	base := filepath.Base(filepath.ToSlash(rel))
	return strings.HasPrefix(base, ".chrootctl-module-") || strings.HasSuffix(base, ".zip") || strings.HasSuffix(base, ".zip.tmp")
}

func cleanManifestPath(rel string) (string, error) {
	if rel == "" || filepath.IsAbs(rel) || strings.HasPrefix(rel, "/") || strings.HasPrefix(rel, "\\") {
		return "", fmt.Errorf("unsafe module package path: %s", rel)
	}
	clean := filepath.ToSlash(filepath.Clean(filepath.FromSlash(rel)))
	if clean == "." || clean == ModulePackageManifestPath || strings.HasPrefix(clean, "../") || clean == ".." {
		return "", fmt.Errorf("unsafe module package path: %s", rel)
	}
	for _, part := range strings.Split(clean, "/") {
		if part == "" || part == "." || part == ".." {
			return "", fmt.Errorf("unsafe module package path: %s", rel)
		}
	}
	return clean, nil
}

func moduleFiles(root string) ([]modulePackageFile, error) {
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	files := []modulePackageFile{}
	err = filepath.WalkDir(absRoot, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if path == absRoot {
			return nil
		}
		if d.Type()&os.ModeSymlink != 0 {
			rel, _ := filepath.Rel(absRoot, path)
			return fmt.Errorf("module package symlink forbidden: %s", filepath.ToSlash(rel))
		}
		if d.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(absRoot, path)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		if rel == ModulePackageManifestPath || ignoredLocalArtifact(rel) {
			return nil
		}
		clean, err := cleanManifestPath(rel)
		if err != nil {
			return err
		}
		st, err := safeRegular(path)
		if err != nil {
			return err
		}
		sum, err := shaFile(path)
		if err != nil {
			return err
		}
		mode := st.Mode().Perm()
		files = append(files, modulePackageFile{Path: clean, Size: st.Size(), SHA256: sum, Mode: fmt.Sprintf("%04o", mode), Executable: mode&0111 != 0})
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Slice(files, func(i, j int) bool { return files[i].Path < files[j].Path })
	return files, nil
}

func packageManifestFor(root string, startupTargets []string) (modulePackageManifest, error) {
	files, err := moduleFiles(root)
	if err != nil {
		return modulePackageManifest{}, err
	}
	targets := append([]string(nil), startupTargets...)
	sort.Strings(targets)
	return modulePackageManifest{
		SchemaVersion:         ModulePackageSchemaVersion,
		ModuleID:              ModuleID,
		ModuleName:            ModuleName,
		ModuleVersion:         ModuleVersion,
		ModuleVersionCode:     ModuleVersionCode,
		BackendVersion:        BackendVersion,
		BridgeProtocolVersion: BridgeProtocolVersion,
		RuntimeSchemaVersion:  RuntimeSchemaVersion,
		RuntimeKind:           RuntimeKind,
		RuntimeABI:            RuntimeABI,
		RuntimeEntrypoint:     RuntimeEntrypoint,
		StartupTargets:        targets,
		Files:                 files,
	}, nil
}

func writePackageManifest(root string, startupTargets []string) error {
	manifest, err := packageManifestFor(root, startupTargets)
	if err != nil {
		return err
	}
	raw, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	return writeFile(root, ModulePackageManifestPath, string(raw), 0644)
}

func readPackageManifest(root string) (modulePackageManifest, error) {
	var got modulePackageManifest
	raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(ModulePackageManifestPath)))
	if err != nil {
		return got, err
	}
	if err = json.Unmarshal(raw, &got); err != nil {
		return got, fmt.Errorf("decode module package manifest: %w", err)
	}
	return got, nil
}

func bootTargets(root string) ([]string, error) {
	raw, err := os.ReadFile(filepath.Join(root, "config/chrootctl/boot_targets.json"))
	if err != nil {
		return nil, err
	}
	var payload struct {
		StartupTargets []string `json:"startup_targets"`
	}
	if err = json.Unmarshal(raw, &payload); err != nil {
		return nil, err
	}
	targets := append([]string(nil), payload.StartupTargets...)
	sort.Strings(targets)
	return targets, nil
}

func comparePackageManifests(got, want modulePackageManifest) error {
	if got.SchemaVersion != want.SchemaVersion || got.ModuleID != want.ModuleID || got.ModuleName != want.ModuleName || got.ModuleVersion != want.ModuleVersion || got.ModuleVersionCode != want.ModuleVersionCode || got.BackendVersion != want.BackendVersion || got.BridgeProtocolVersion != want.BridgeProtocolVersion || got.RuntimeSchemaVersion != want.RuntimeSchemaVersion || got.RuntimeKind != want.RuntimeKind || got.RuntimeABI != want.RuntimeABI || got.RuntimeEntrypoint != want.RuntimeEntrypoint {
		return errors.New("module package manifest identity mismatch")
	}
	if strings.Join(got.StartupTargets, "\x00") != strings.Join(want.StartupTargets, "\x00") {
		return fmt.Errorf("module package startup targets mismatch: %v != %v", got.StartupTargets, want.StartupTargets)
	}
	if len(got.Files) != len(want.Files) {
		return fmt.Errorf("module package file count mismatch: %d != %d", len(got.Files), len(want.Files))
	}
	for i := range got.Files {
		if got.Files[i] != want.Files[i] {
			return fmt.Errorf("module package file seal mismatch at %d: %+v != %+v", i, got.Files[i], want.Files[i])
		}
	}
	return nil
}

func ValidatePackageManifest(root string) error {
	got, err := readPackageManifest(root)
	if err != nil {
		return err
	}
	targets, err := bootTargets(root)
	if err != nil {
		return err
	}
	want, err := packageManifestFor(root, targets)
	if err != nil {
		return err
	}
	if err = comparePackageManifests(got, want); err != nil {
		return err
	}
	seen := map[string]bool{}
	for _, f := range got.Files {
		seen[f.Path] = true
	}
	for _, required := range requiredModuleFiles() {
		if !seen[required] {
			return fmt.Errorf("module package manifest missing required file: %s", required)
		}
	}
	return nil
}

func ValidateZipArchive(path string) error {
	zr, err := zip.OpenReader(path)
	if err != nil {
		return err
	}
	defer zr.Close()
	type entry struct {
		meta modulePackageFile
		raw  []byte
	}
	entries := map[string]entry{}
	for _, f := range zr.File {
		if f.FileInfo().IsDir() {
			return fmt.Errorf("module ZIP directory entries are forbidden: %s", f.Name)
		}
		if f.FileInfo().Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("module ZIP symlink forbidden: %s", f.Name)
		}
		clean := filepath.ToSlash(filepath.Clean(f.Name))
		if clean != f.Name || strings.HasPrefix(clean, "../") || clean == "." || filepath.IsAbs(clean) {
			return fmt.Errorf("unsafe module ZIP entry path: %s", f.Name)
		}
		if _, ok := entries[clean]; ok {
			return fmt.Errorf("duplicate module ZIP entry: %s", clean)
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		data, err := io.ReadAll(rc)
		rc.Close()
		if err != nil {
			return err
		}
		mode := f.FileInfo().Mode().Perm()
		sum := sha256.Sum256(data)
		entries[clean] = entry{meta: modulePackageFile{Path: clean, Size: int64(len(data)), SHA256: hex.EncodeToString(sum[:]), Mode: fmt.Sprintf("%04o", mode), Executable: mode&0111 != 0}, raw: data}
	}
	manifestEntry, ok := entries[ModulePackageManifestPath]
	if !ok {
		return fmt.Errorf("module ZIP missing %s", ModulePackageManifestPath)
	}
	var got modulePackageManifest
	if err = json.Unmarshal(manifestEntry.raw, &got); err != nil {
		return fmt.Errorf("decode module package manifest from ZIP: %w", err)
	}
	bootEntry, ok := entries["config/chrootctl/boot_targets.json"]
	if !ok {
		return errors.New("module ZIP missing config/chrootctl/boot_targets.json")
	}
	var bootPayload struct {
		StartupTargets []string `json:"startup_targets"`
	}
	if err = json.Unmarshal(bootEntry.raw, &bootPayload); err != nil {
		return fmt.Errorf("decode module boot targets from ZIP: %w", err)
	}
	bootTargets := append([]string(nil), bootPayload.StartupTargets...)
	sort.Strings(bootTargets)
	gotTargets := append([]string(nil), got.StartupTargets...)
	sort.Strings(gotTargets)
	if strings.Join(gotTargets, "\x00") != strings.Join(bootTargets, "\x00") {
		return fmt.Errorf("module ZIP package manifest startup targets do not match boot target manifest: %v != %v", got.StartupTargets, bootPayload.StartupTargets)
	}
	files := make([]modulePackageFile, 0, len(entries)-1)
	for name, ent := range entries {
		if name == ModulePackageManifestPath {
			continue
		}
		if _, err := cleanManifestPath(name); err != nil {
			return err
		}
		files = append(files, ent.meta)
	}
	sort.Slice(files, func(i, j int) bool { return files[i].Path < files[j].Path })
	want := modulePackageManifest{SchemaVersion: ModulePackageSchemaVersion, ModuleID: ModuleID, ModuleName: ModuleName, ModuleVersion: ModuleVersion, ModuleVersionCode: ModuleVersionCode, BackendVersion: BackendVersion, BridgeProtocolVersion: BridgeProtocolVersion, RuntimeSchemaVersion: RuntimeSchemaVersion, RuntimeKind: RuntimeKind, RuntimeABI: RuntimeABI, RuntimeEntrypoint: RuntimeEntrypoint, StartupTargets: append([]string(nil), got.StartupTargets...), Files: files}
	sort.Strings(want.StartupTargets)
	if err = comparePackageManifests(got, want); err != nil {
		return err
	}
	for _, required := range requiredModuleFiles() {
		if _, ok := entries[required]; !ok {
			return fmt.Errorf("module ZIP missing required file: %s", required)
		}
	}
	return nil
}
func moduleProp() string {
	return fmt.Sprintf("id=%s\nname=%s\nversion=%s\nversionCode=%d\nauthor=chrootctl\ndescription=Self-contained chrootctl Magisk/KernelSU runtime with a bundled Android Go backend.\n", ModuleID, ModuleName, ModuleVersion, ModuleVersionCode)
}
func customize() string {
	return `#!/system/bin/sh
SKIPMOUNT=false
PROPFILE=false
POSTFSDATA=true
LATESTARTSERVICE=true
REPLACE=""
LOG_HELPER="${MODPATH:-}/bin/chrootctl-log-helper"
[ -x "$LOG_HELPER" ] && "$LOG_HELPER" module "installer begin" || true

ui_print "chrootctl ships a bundled Go native runtime." 2>/dev/null || echo "chrootctl ships a bundled Go native runtime."

# Magisk/KernelSU extraction may leave module payload files as 0644 even when
# the ZIP records executable modes. Enforce executable bits during install so
# /system/bin/chrootctl can exec the bundled Go runtime after promotion.
if [ -n "${MODPATH:-}" ] && [ -d "$MODPATH" ]; then
  if command -v set_perm_recursive >/dev/null 2>&1; then
    set_perm_recursive "$MODPATH" 0 0 0755 0644
  else
    chown -R 0:0 "$MODPATH" 2>/dev/null || true
    find "$MODPATH" -type d -exec chmod 0755 {} + 2>/dev/null || true
    find "$MODPATH" -type f -exec chmod 0644 {} + 2>/dev/null || true
  fi

  if command -v set_perm >/dev/null 2>&1; then
    set_perm "$MODPATH/customize.sh" 0 0 0755
    set_perm "$MODPATH/post-fs-data.sh" 0 0 0755
    set_perm "$MODPATH/service.sh" 0 0 0755
    set_perm "$MODPATH/uninstall.sh" 0 0 0755
    set_perm "$MODPATH/bin/chrootctl-magisk-helper" 0 0 0755
    set_perm "$MODPATH/bin/chrootctl-log-helper" 0 0 0755
    set_perm "$MODPATH/system/bin/chrootctl" 0 0 0755
    set_perm "$MODPATH/system/bin/chrootctl-magisk-helper" 0 0 0755
    set_perm "$MODPATH/runtime/arm64-v8a/chrootctl" 0 0 0755
    [ ! -f "$MODPATH/runtime/arm64-v8a/rclone" ] || set_perm "$MODPATH/runtime/arm64-v8a/rclone" 0 0 0755
  else
    chmod 0755 "$MODPATH/customize.sh" 2>/dev/null || true
    chmod 0755 "$MODPATH/post-fs-data.sh" 2>/dev/null || true
    chmod 0755 "$MODPATH/service.sh" 2>/dev/null || true
    chmod 0755 "$MODPATH/uninstall.sh" 2>/dev/null || true
    chmod 0755 "$MODPATH/bin/chrootctl-magisk-helper" 2>/dev/null || true
    chmod 0755 "$MODPATH/bin/chrootctl-log-helper" 2>/dev/null || true
    chmod 0755 "$MODPATH/system/bin/chrootctl" 2>/dev/null || true
    chmod 0755 "$MODPATH/system/bin/chrootctl-magisk-helper" 2>/dev/null || true
    chmod 0755 "$MODPATH/runtime/arm64-v8a/chrootctl" 2>/dev/null || true
    [ ! -f "$MODPATH/runtime/arm64-v8a/rclone" ] || chmod 0755 "$MODPATH/runtime/arm64-v8a/rclone" 2>/dev/null || true
  fi

  # Existing installs are live-updated as well as left staged for the root
  # manager.  Build a complete sibling from the active tree first, overlay
  # only module-owned payload paths, then swap directories with rename(2).
  # This preserves manager marker files and gives us a rollback point.
  ACTIVE_MODULE="/data/adb/modules/chrootctl-magisk"
  if [ -d "$ACTIVE_MODULE" ] && [ "$MODPATH" != "$ACTIVE_MODULE" ]; then
    LIVE_PARENT="${ACTIVE_MODULE%/*}"
    LIVE_NEXT="$LIVE_PARENT/.chrootctl-magisk.live-new.$$"
    LIVE_OLD="$LIVE_PARENT/.chrootctl-magisk.live-old.$$"
    LIVE_OK=1
    rm -rf "$LIVE_NEXT" "$LIVE_OLD" 2>/dev/null || true
    mkdir -p "$LIVE_NEXT" || LIVE_OK=0
    [ "$LIVE_OK" -eq 0 ] || cp -a "$ACTIVE_MODULE/." "$LIVE_NEXT/" || LIVE_OK=0

    if [ "$LIVE_OK" -eq 1 ]; then
      for rel in module.prop customize.sh post-fs-data.sh service.sh uninstall.sh bin system config runtime webroot; do
        rm -rf "$LIVE_NEXT/$rel" || { LIVE_OK=0; break; }
        [ ! -e "$MODPATH/$rel" ] || cp -a "$MODPATH/$rel" "$LIVE_NEXT/$rel" || { LIVE_OK=0; break; }
      done
    fi

    for required in module.prop post-fs-data.sh service.sh system/bin/chrootctl runtime/arm64-v8a/runtime-manifest.json runtime/arm64-v8a/chrootctl config/chrootctl/module-package-manifest.json; do
      [ "$LIVE_OK" -eq 0 ] || [ -f "$LIVE_NEXT/$required" ] || LIVE_OK=0
    done
    [ "$LIVE_OK" -eq 0 ] || [ -x "$LIVE_NEXT/system/bin/chrootctl" ] || LIVE_OK=0
    [ "$LIVE_OK" -eq 0 ] || [ -x "$LIVE_NEXT/runtime/arm64-v8a/chrootctl" ] || LIVE_OK=0

    if [ "$LIVE_OK" -eq 1 ]; then
      chown -R 0:0 "$LIVE_NEXT" 2>/dev/null || true
      restorecon -RF "$LIVE_NEXT" 2>/dev/null || true
      if mv "$ACTIVE_MODULE" "$LIVE_OLD" && mv "$LIVE_NEXT" "$ACTIVE_MODULE"; then
        rm -rf "$LIVE_OLD" 2>/dev/null || true
        export CHROOTCTL_MODULE_DIR="$ACTIVE_MODULE"
        "$ACTIVE_MODULE/post-fs-data.sh" >/dev/null 2>&1 || true
        if [ ! -e "$ACTIVE_MODULE/disable" ] && [ ! -e "$ACTIVE_MODULE/remove" ]; then
          "$ACTIVE_MODULE/service.sh" >/dev/null 2>&1 || true
        fi
        [ -x "$ACTIVE_MODULE/bin/chrootctl-log-helper" ] && "$ACTIVE_MODULE/bin/chrootctl-log-helper" module "installer live-update success" || true
        ui_print "chrootctl active module updated live; reboot is not required for the module runtime/WebUI." 2>/dev/null || echo "chrootctl active module updated live; reboot is not required for the module runtime/WebUI."
        ui_print "Root-manager magic-mount changes, if any, may still require a reboot." 2>/dev/null || true
      else
        rm -rf "$LIVE_NEXT" 2>/dev/null || true
        if [ ! -d "$ACTIVE_MODULE" ] && [ -d "$LIVE_OLD" ]; then mv "$LIVE_OLD" "$ACTIVE_MODULE" 2>/dev/null || true; fi
        [ -x "$LOG_HELPER" ] && "$LOG_HELPER" module "installer live-update failed staged-fallback=true" || true
        ui_print "chrootctl live activation failed; staged update is preserved for reboot activation." 2>/dev/null || echo "chrootctl live activation failed; staged update is preserved for reboot activation."
      fi
    else
      rm -rf "$LIVE_NEXT" "$LIVE_OLD" 2>/dev/null || true
      [ -x "$LOG_HELPER" ] && "$LOG_HELPER" module "installer live-update preflight-failed staged-fallback=true" || true
      ui_print "chrootctl live activation preflight failed; staged update is preserved for reboot activation." 2>/dev/null || true
    fi
  fi
fi

return 0 2>/dev/null || exit 0
`
}

func postFS() string {
	return `#!/system/bin/sh
set -u
MODDIR="${CHROOTCTL_MODULE_DIR:-/data/adb/modules/chrootctl-magisk}"
STATE_ROOT=/data/adb/chrootctl
[ -n "${CHROOTCTL_STATE_ROOT:-}" ] && STATE_ROOT="$CHROOTCTL_STATE_ROOT"
BIN_DIR="$STATE_ROOT/bin"
RCLONE_DIR="$STATE_ROOT/rclone"
PUBLIC="$BIN_DIR/chrootctl"
SOURCE="$MODDIR/system/bin/chrootctl"
LOG_HELPER="$MODDIR/bin/chrootctl-log-helper"
[ -x "$LOG_HELPER" ] && "$LOG_HELPER" module "post-fs-data begin module=$MODDIR" || true

# KernelSU legacy does not necessarily expose module system/bin through magic
# mount. Maintain a root-owned stable launcher outside the module mount tree.
[ -d "$MODDIR" ] || exit 0
[ -f "$SOURCE" ] && [ -x "$SOURCE" ] && [ ! -L "$SOURCE" ] || exit 0
mkdir -p "$BIN_DIR" "$RCLONE_DIR" || exit 0
chown 0:0 "$STATE_ROOT" "$BIN_DIR" "$RCLONE_DIR" 2>/dev/null || true
chmod 0700 "$STATE_ROOT" "$BIN_DIR" "$RCLONE_DIR" 2>/dev/null || true
[ ! -f "$RCLONE_DIR/rclone.conf" ] || { chown 0:0 "$RCLONE_DIR/rclone.conf" 2>/dev/null || true; chmod 0600 "$RCLONE_DIR/rclone.conf" 2>/dev/null || true; }
cat > "$PUBLIC.tmp" <<'EOF'
#!/system/bin/sh
MODDIR="${CHROOTCTL_MODULE_DIR:-/data/adb/modules/chrootctl-magisk}"
exec "$MODDIR/system/bin/chrootctl" "$@"
EOF
chown 0:0 "$PUBLIC.tmp" 2>/dev/null || true
chmod 0755 "$PUBLIC.tmp" || { rm -f "$PUBLIC.tmp"; exit 0; }
mv -f "$PUBLIC.tmp" "$PUBLIC"
restorecon "$PUBLIC" 2>/dev/null || true
[ -x "$LOG_HELPER" ] && "$LOG_HELPER" module "post-fs-data stable-launcher-refreshed" || true
exit 0
`
}
func uninstall() string {
	return "#!/system/bin/sh\nset -u\nLOGGER=/data/adb/modules/chrootctl-magisk/bin/chrootctl-log-helper\n[ -x \"$LOGGER\" ] && \"$LOGGER\" module \"uninstall begin\" || true\nSTATE_ROOT=/data/adb/chrootctl\n[ -n \"${CHROOTCTL_STATE_ROOT:-}\" ] && STATE_ROOT=\"$CHROOTCTL_STATE_ROOT\"\nif [ -d \"$STATE_ROOT\" ]; then\n  rm -f \"$STATE_ROOT/bin/chrootctl\" 2>/dev/null || true\n  rmdir \"$STATE_ROOT/bin\" 2>/dev/null || true\n  rm -f \"$STATE_ROOT/control.state\" \"$STATE_ROOT/android-app.enabled\" \"$STATE_ROOT/clipboard-daemon.pid\" \"$STATE_ROOT/clipboard-daemon.token\" \"$STATE_ROOT/clipboard-daemon.identity.json\" 2>/dev/null || true\n  rm -f \"$STATE_ROOT/clipboard.sock\" 2>/dev/null || true\nfi\nexit 0\n"
}

func logHelper() string {
	return `#!/system/bin/sh
set -u
CHANNEL="${1:-module}"
shift 2>/dev/null || true
case "$CHANNEL" in module|transport) ;; *) CHANNEL=module ;; esac
LOG_ROOT="${CHROOTCTL_LOG_ROOT:-/data/local/tmp/chrootctl}"
LOG_FILE="$LOG_ROOT/$CHANNEL.log"
MAX_BYTES="${CHROOTCTL_LOG_MAX_BYTES:-1048576}"
KEEP="${CHROOTCTL_LOG_KEEP:-5}"
mkdir -p "$LOG_ROOT" 2>/dev/null || exit 0
chmod 0700 "$LOG_ROOT" 2>/dev/null || true
if [ -f "$LOG_FILE" ]; then
  size="$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)"
  if [ "${size:-0}" -gt "$MAX_BYTES" ]; then
    i="$KEEP"
    while [ "$i" -gt 1 ]; do
      prev=$((i - 1))
      [ ! -f "$LOG_FILE.$prev" ] || mv -f "$LOG_FILE.$prev" "$LOG_FILE.$i" 2>/dev/null || true
      i="$prev"
    done
    mv -f "$LOG_FILE" "$LOG_FILE.1" 2>/dev/null || true
  fi
fi
ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date 2>/dev/null || echo unknown)"
printf '%s pid=%s %s\n' "$ts" "$$" "$*" >> "$LOG_FILE" 2>/dev/null || true
chmod 0600 "$LOG_FILE" 2>/dev/null || true
exit 0
`
}

func helper() string {
	return "#!/system/bin/sh\nset -u\nCMD=\"${1:-}\"\nshift 2>/dev/null || true\nMODDIR=\"${CHROOTCTL_MODULE_DIR:-${0%/bin/*}}\"\nCHROOTCTL=\"$MODDIR/system/bin/chrootctl\"\nLOGGER=\"$MODDIR/bin/chrootctl-log-helper\"\n[ -x \"$CHROOTCTL\" ] || { [ -x \"$LOGGER\" ] && \"$LOGGER\" module \"helper runtime-unavailable\" || true; echo \"bundled chrootctl runtime is unavailable\" >&2; exit 127; }\ncase \"$CMD\" in\n  __module-boot|__module-service)\n    [ -x \"$LOGGER\" ] && \"$LOGGER\" module \"helper begin command=$CMD targets=$#\" || true\n    rc=0\n    \"$CHROOTCTL\" clipboard daemon start >/dev/null 2>&1 || true\n    for target in \"$@\"; do\n      \"$CHROOTCTL\" --name \"$target\" mount || rc=1\n    done\n    \"$CHROOTCTL\" run --boot || rc=1\n    [ -x \"$LOGGER\" ] && \"$LOGGER\" module \"helper end command=$CMD rc=$rc\" || true\n    exit \"$rc\"\n    ;;\n  *)\n    echo \"unsupported chrootctl module helper command: $CMD\" >&2\n    exit 2\n    ;;\nesac\n"
}
func launcher() string {
	return "#!/system/bin/sh\nset -eu\n\nMODULE_ID=\"chrootctl-magisk\"\nRUNTIME_ABI=\"arm64-v8a\"\nACTIVE_MODULE=\"/data/adb/modules/chrootctl-magisk\"\nUPDATE_MODULE=\"/data/adb/modules_update/chrootctl-magisk\"\n\nruntime_bin_ok() {\n  [ -f \"$1\" ] && [ -x \"$1\" ] && [ ! -L \"$1\" ]\n}\n\nMODDIR=\"${CHROOTCTL_MODULE_DIR:-}\"\nif [ -z \"$MODDIR\" ]; then\n  case \"$0\" in\n    */system/bin/chrootctl) MODDIR=\"${0%/system/bin/chrootctl}\" ;;\n  esac\nfi\ncase \"$MODDIR\" in\n  \"\"|/system|/system_root/system) MODDIR=\"$ACTIVE_MODULE\" ;;\nesac\n\nLOGGER=\"$MODDIR/bin/chrootctl-log-helper\"\nCOMMAND=\"${1:-none}\"\nSUBCOMMAND=\"\"\n[ \"$COMMAND\" != \"app\" ] || SUBCOMMAND=\"${2:-}\"\n[ -x \"$LOGGER\" ] && \"$LOGGER\" transport \"invoke command=$COMMAND subcommand=$SUBCOMMAND argc=$#\" || true\n\nRUNTIME_ROOT=\"$MODDIR/runtime/$RUNTIME_ABI\"\nRUNTIME_MANIFEST=\"$RUNTIME_ROOT/runtime-manifest.json\"\nRUNTIME_BIN=\"$RUNTIME_ROOT/chrootctl\"\n\n[ -d \"$RUNTIME_ROOT\" ] && [ ! -L \"$RUNTIME_ROOT\" ] || { echo \"bundled native runtime directory is missing or unsafe: $RUNTIME_ROOT\" >&2; echo \"hint: verify the active module live-update completed; a preserved modules_update tree can still activate on reboot.\" >&2; exit 127; }\n[ -f \"$RUNTIME_MANIFEST\" ] && [ ! -L \"$RUNTIME_MANIFEST\" ] || { echo \"bundled native runtime manifest is missing or unsafe: $RUNTIME_MANIFEST\" >&2; echo \"hint: rebuild/reinstall the module from a sealed Go-native runtime.\" >&2; exit 127; }\nruntime_bin_ok \"$RUNTIME_BIN\" || { echo \"bundled native chrootctl executable is missing or unsafe: $RUNTIME_BIN\" >&2; echo \"hint: verify the active module live-update completed and the runtime has executable mode; reboot remains a fallback for staged activation.\" >&2; exit 127; }\n\nmkdir -p /data/adb/chrootctl 2>/dev/null || true\nchmod 0700 /data/adb/chrootctl 2>/dev/null || true\n\nexport CHROOTCTL_MODULE_DIR=\"$MODDIR\"\nexec \"$RUNTIME_BIN\" \"$@\"\n"
}
func shellSingleQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\\''") + "'"
}

func service(startupTargets []string) string {
	args := make([]string, 0, len(startupTargets))
	for _, target := range startupTargets {
		args = append(args, shellSingleQuote(target))
	}
	invocation := "\"$HELPER\" __module-service"
	if len(args) > 0 {
		invocation += " " + strings.Join(args, " ")
	}
	return "#!/system/bin/sh\nMODDIR=\"${0%/*}\"\ncase \"$MODDIR\" in\n  */system/bin) MODDIR=\"${MODDIR%/system/bin}\" ;;\nesac\nACTIVE_MODULE=\"/data/adb/modules/chrootctl-magisk\"\nUPDATE_MODULE=\"/data/adb/modules_update/chrootctl-magisk\" # diagnostics only\n\nif [ -n \"${CHROOTCTL_MODULE_DIR:-}\" ]; then\n  MODDIR=\"$CHROOTCTL_MODULE_DIR\"\nelif [ -d \"$ACTIVE_MODULE\" ]; then\n  MODDIR=\"$ACTIVE_MODULE\"\nfi\n\nif [ \"$MODDIR\" != \"$ACTIVE_MODULE\" ]; then\n  echo \"refusing module service outside active module: $MODDIR\" >&2\n  exit 0\nfi\n\nexport CHROOTCTL_MODULE_DIR=\"$MODDIR\"\nHELPER=\"$MODDIR/bin/chrootctl-magisk-helper\"\nLOGGER=\"$MODDIR/bin/chrootctl-log-helper\"\n[ -x \"$HELPER\" ] || { [ -x \"$LOGGER\" ] && \"$LOGGER\" module \"service helper-missing\" || true; exit 0; }\n[ -x \"$LOGGER\" ] && \"$LOGGER\" module \"service begin\" || true\n" + invocation + " || true\n[ -x \"$LOGGER\" ] && \"$LOGGER\" module \"service end\" || true\n"
}
func proxy(target string) string {
	return "#!/system/bin/sh\nMODDIR=\"${CHROOTCTL_MODULE_DIR:-/data/adb/modules/chrootctl-magisk}\"\nexec \"$MODDIR/" + target + "\" \"$@\"\n"
}

func Render(opts Options) error {
	if opts.OutputDir == "" {
		return errors.New("module output directory is required")
	}
	out, _ := filepath.Abs(opts.OutputDir)
	runtime := opts.NativeRuntimeDir
	if runtime == "" {
		cwd, _ := os.Getwd()
		runtime = filepath.Join(cwd, "out", "native-runtime", RuntimeABI)
	}
	runtime, _ = filepath.Abs(runtime)
	if e := ValidateRuntime(runtime); e != nil {
		return e
	}
	seenTargets := map[string]bool{}
	cleanTargets := make([]string, 0, len(opts.StartupTargets))
	for _, target := range opts.StartupTargets {
		name, e := validation.ChrootName(strings.TrimSpace(target))
		if e != nil {
			return fmt.Errorf("invalid module startup target %q: %w", target, e)
		}
		if !seenTargets[name] {
			seenTargets[name] = true
			cleanTargets = append(cleanTargets, name)
		}
	}
	opts.StartupTargets = cleanTargets
	if st, e := os.Lstat(out); e == nil {
		if st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
			return errors.New("unsafe module output directory")
		}
		ents, _ := os.ReadDir(out)
		if len(ents) > 0 {
			return errors.New("refusing to replace non-empty module output directory")
		}
	} else if !os.IsNotExist(e) {
		return e
	} else if e = os.MkdirAll(out, 0755); e != nil {
		return e
	}
	compat, _ := json.MarshalIndent(CompatibilityPayload(), "", "  ")
	compat = append(compat, '\n')
	targets, _ := json.MarshalIndent(map[string]any{"startup_targets": opts.StartupTargets}, "", "  ")
	targets = append(targets, '\n')
	files := map[string]struct {
		c string
		m fs.FileMode
	}{"module.prop": {moduleProp(), 0644}, "customize.sh": {customize(), 0755}, "post-fs-data.sh": {postFS(), 0755}, "service.sh": {service(opts.StartupTargets), 0755}, "uninstall.sh": {uninstall(), 0755}, "bin/chrootctl-magisk-helper": {helper(), 0755}, "bin/chrootctl-log-helper": {logHelper(), 0755}, "system/bin/chrootctl": {launcher(), 0755}, "system/bin/chrootctl-magisk-helper": {proxy("bin/chrootctl-magisk-helper"), 0755}, "config/chrootctl/compatibility-manifest.json": {string(compat), 0644}, "config/chrootctl/boot_targets.json": {string(targets), 0644}}
	for rel, v := range files {
		if e := writeFile(out, rel, v.c, v.m); e != nil {
			return e
		}
	}
	if e := writeWebUI(out); e != nil {
		return e
	}
	dst := filepath.Join(out, "runtime", RuntimeABI)
	if e := os.MkdirAll(dst, 0755); e != nil {
		return e
	}
	entries, e := os.ReadDir(runtime)
	if e != nil {
		return e
	}
	for _, ent := range entries {
		src := filepath.Join(runtime, ent.Name())
		st, e := os.Lstat(src)
		if e != nil {
			return e
		}
		if st.Mode()&os.ModeSymlink != 0 || !st.Mode().IsRegular() {
			return fmt.Errorf("unsafe runtime source: %s", src)
		}
		data, e := os.ReadFile(src)
		if e != nil {
			return e
		}
		mode := fs.FileMode(0644)
		if st.Mode().Perm()&0111 != 0 {
			mode = 0755
		}
		if e = os.WriteFile(filepath.Join(dst, ent.Name()), data, mode); e != nil {
			return e
		}
	}
	if e := ValidateRuntime(dst); e != nil {
		return e
	}
	if e := writePackageManifest(out, opts.StartupTargets); e != nil {
		return e
	}
	if e := ValidateRendered(out); e != nil {
		return e
	}
	if opts.ZipPath != "" {
		return Zip(out, opts.ZipPath)
	}
	return nil
}

func Zip(root, path string) error {
	if e := ValidateRendered(root); e != nil {
		return e
	}
	absRoot, e := filepath.Abs(root)
	if e != nil {
		return e
	}
	absZip, e := filepath.Abs(path)
	if e != nil {
		return e
	}
	var names []string
	if e = filepath.WalkDir(absRoot, func(p string, d fs.DirEntry, e error) error {
		if e != nil || d.IsDir() {
			return e
		}
		absPath, e := filepath.Abs(p)
		if e != nil {
			return e
		}
		if absPath == absZip {
			return nil
		}
		rel, e := filepath.Rel(absRoot, p)
		if e != nil {
			return e
		}
		relSlash := filepath.ToSlash(rel)
		if ignoredLocalArtifact(relSlash) {
			return nil
		}
		names = append(names, relSlash)
		return nil
	}); e != nil {
		return e
	}
	if e := os.MkdirAll(filepath.Dir(absZip), 0755); e != nil {
		return e
	}
	tmp, e := os.CreateTemp(filepath.Dir(absZip), ".chrootctl-module-*.zip.tmp")
	if e != nil {
		return e
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	zw := zip.NewWriter(tmp)
	sort.Strings(names)
	epoch := time.Date(1980, 1, 1, 0, 0, 0, 0, time.UTC)
	for _, name := range names {
		p := filepath.Join(absRoot, filepath.FromSlash(name))
		st, e := safeRegular(p)
		if e != nil {
			zw.Close()
			tmp.Close()
			return e
		}
		h, _ := zip.FileInfoHeader(st)
		h.Name = name
		h.Method = zip.Deflate
		h.Modified = epoch
		h.SetMode(st.Mode().Perm())
		w, e := zw.CreateHeader(h)
		if e != nil {
			zw.Close()
			tmp.Close()
			return e
		}
		src, e := os.Open(p)
		if e != nil {
			zw.Close()
			tmp.Close()
			return e
		}
		_, e = io.Copy(w, src)
		src.Close()
		if e != nil {
			zw.Close()
			tmp.Close()
			return e
		}
	}
	if e = zw.Close(); e != nil {
		tmp.Close()
		return e
	}
	if e = tmp.Close(); e != nil {
		return e
	}
	if e = os.Rename(tmpName, absZip); e != nil {
		return e
	}
	return nil
}
func ValidateRendered(root string) error {
	required := append(requiredModuleFiles(), ModulePackageManifestPath)
	for _, rel := range required {
		if _, e := safeRegular(filepath.Join(root, filepath.FromSlash(rel))); e != nil {
			return e
		}
	}
	if e := ValidateRuntime(filepath.Join(root, "runtime", RuntimeABI)); e != nil {
		return e
	}
	return ValidatePackageManifest(root)
}
