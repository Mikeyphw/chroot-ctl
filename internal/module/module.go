package module

import (
	"archive/zip"
	"crypto/sha256"
	"debug/elf"
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
	ModuleVersion         = "1.3.0"
	ModuleVersionCode     = 15
	BackendVersion        = "0.11.0"
	BridgeProtocolVersion = 1
	RuntimeSchemaVersion  = 2
	RuntimeKind           = "go-native"
	RuntimeABI            = "arm64-v8a"
	RuntimeEntrypoint     = "chrootctl"
)

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

func CompatibilityPayload() map[string]any {
	return map[string]any{
		"schemaVersion":         3,
		"project":               "chrootctl",
		"bridgeProtocolVersion": BridgeProtocolVersion,
		"backend":               map[string]any{"implementation": "go", "version": BackendVersion},
		"nativeRuntime":         map[string]any{"schemaVersion": RuntimeSchemaVersion, "kind": RuntimeKind, "platform": "android", "abi": RuntimeABI, "entrypoint": RuntimeEntrypoint},
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
	ef, e := elf.Open(ep)
	if e != nil {
		return fmt.Errorf("native runtime entrypoint is not a valid ELF: %w", e)
	}
	defer ef.Close()
	if ef.Class != elf.ELFCLASS64 || ef.Data != elf.ELFDATA2LSB || ef.Machine != elf.EM_AARCH64 || ef.Type != elf.ET_DYN {
		return fmt.Errorf("native runtime ELF identity mismatch: class=%s data=%s machine=%s type=%s", ef.Class, ef.Data, ef.Machine, ef.Type)
	}
	interpreter := ""
	for _, prog := range ef.Progs {
		if prog.Type != elf.PT_INTERP {
			continue
		}
		raw, readErr := io.ReadAll(io.LimitReader(prog.Open(), 256))
		if readErr != nil {
			return fmt.Errorf("read native runtime interpreter: %w", readErr)
		}
		interpreter = strings.TrimRight(string(raw), "\x00")
		break
	}
	if interpreter != "/system/bin/linker64" {
		return fmt.Errorf("native runtime Android interpreter mismatch: %q", interpreter)
	}
	return nil
}

func writeFile(root, rel, content string, mode fs.FileMode) error {
	p := filepath.Join(root, filepath.FromSlash(rel))
	if e := os.MkdirAll(filepath.Dir(p), 0755); e != nil {
		return e
	}
	return os.WriteFile(p, []byte(content), mode)
}
func moduleProp() string {
	return fmt.Sprintf("id=%s\nname=%s\nversion=%s\nversionCode=%d\nauthor=chrootctl\ndescription=Self-contained chrootctl Magisk/KernelSU runtime with a bundled Android Go backend.\n", ModuleID, ModuleName, ModuleVersion, ModuleVersionCode)
}
func customize() string {
	return "#!/system/bin/sh\nSKIPMOUNT=false\nPROPFILE=false\nPOSTFSDATA=true\nLATESTARTSERVICE=true\nREPLACE=\"\"\nui_print \"chrootctl ships a bundled Go native runtime.\" 2>/dev/null || echo \"chrootctl ships a bundled Go native runtime.\"\nreturn 0 2>/dev/null || exit 0\n"
}
func postFS() string { return "#!/system/bin/sh\nexit 0\n" }
func helper() string {
	return "#!/system/bin/sh\nset -u\nCMD=\"${1:-}\"\nshift 2>/dev/null || true\nMODDIR=\"${CHROOTCTL_MODULE_DIR:-${0%/bin/*}}\"\nCHROOTCTL=\"$MODDIR/system/bin/chrootctl\"\n[ -x \"$CHROOTCTL\" ] || { echo \"bundled chrootctl runtime is unavailable\" >&2; exit 127; }\ncase \"$CMD\" in\n  __module-boot|__module-service)\n    rc=0\n    \"$CHROOTCTL\" clipboard daemon start >/dev/null 2>&1 || true\n    for target in \"$@\"; do\n      \"$CHROOTCTL\" --name \"$target\" mount || rc=1\n    done\n    \"$CHROOTCTL\" run --boot || rc=1\n    exit \"$rc\"\n    ;;\n  *)\n    echo \"unsupported chrootctl module helper command: $CMD\" >&2\n    exit 2\n    ;;\nesac\n"
}
func launcher() string {
	return "#!/system/bin/sh\nset -eu\n\nMODULE_ID=\"chrootctl-magisk\"\nRUNTIME_ABI=\"arm64-v8a\"\nACTIVE_MODULE=\"/data/adb/modules/chrootctl-magisk\"\nUPDATE_MODULE=\"/data/adb/modules_update/chrootctl-magisk\" # diagnostics only\n\nMODDIR=\"${CHROOTCTL_MODULE_DIR:-}\"\nif [ -z \"$MODDIR\" ]; then\n  MODDIR=\"$ACTIVE_MODULE\"\nfi\n\nRUNTIME_ROOT=\"$MODDIR/runtime/$RUNTIME_ABI\"\nRUNTIME_MANIFEST=\"$RUNTIME_ROOT/runtime-manifest.json\"\nRUNTIME_BIN=\"$RUNTIME_ROOT/chrootctl\"\n\n[ -d \"$RUNTIME_ROOT\" ] && [ ! -L \"$RUNTIME_ROOT\" ] || { echo \"bundled native runtime directory is missing or unsafe\" >&2; exit 127; }\n[ -f \"$RUNTIME_MANIFEST\" ] && [ ! -L \"$RUNTIME_MANIFEST\" ] || { echo \"bundled native runtime manifest is missing or unsafe\" >&2; exit 127; }\n[ -f \"$RUNTIME_BIN\" ] && [ -x \"$RUNTIME_BIN\" ] && [ ! -L \"$RUNTIME_BIN\" ] || { echo \"bundled native chrootctl executable is missing or unsafe\" >&2; exit 127; }\n\nmkdir -p /data/adb/chrootctl 2>/dev/null || true\nchmod 0700 /data/adb/chrootctl 2>/dev/null || true\n\nexport CHROOTCTL_MODULE_DIR=\"$MODDIR\"\nexec \"$RUNTIME_BIN\" \"$@\"\n"
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
	return "#!/system/bin/sh\nMODDIR=\"${0%/*}\"\ncase \"$MODDIR\" in\n  */system/bin) MODDIR=\"${MODDIR%/system/bin}\" ;;\nesac\nACTIVE_MODULE=\"/data/adb/modules/chrootctl-magisk\"\nUPDATE_MODULE=\"/data/adb/modules_update/chrootctl-magisk\" # diagnostics only\n\nif [ -n \"${CHROOTCTL_MODULE_DIR:-}\" ]; then\n  MODDIR=\"$CHROOTCTL_MODULE_DIR\"\nelif [ -d \"$ACTIVE_MODULE\" ]; then\n  MODDIR=\"$ACTIVE_MODULE\"\nfi\n\nif [ \"$MODDIR\" != \"$ACTIVE_MODULE\" ]; then\n  echo \"refusing module service outside active module: $MODDIR\" >&2\n  exit 0\nfi\n\nexport CHROOTCTL_MODULE_DIR=\"$MODDIR\"\nHELPER=\"$MODDIR/bin/chrootctl-magisk-helper\"\n[ -x \"$HELPER\" ] || exit 0\n" + invocation + " || true\n"
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
	}{"module.prop": {moduleProp(), 0644}, "customize.sh": {customize(), 0755}, "post-fs-data.sh": {postFS(), 0755}, "service.sh": {service(opts.StartupTargets), 0755}, "bin/chrootctl-magisk-helper": {helper(), 0755}, "system/bin/chrootctl": {launcher(), 0755}, "system/bin/chrootctl-magisk-helper": {proxy("bin/chrootctl-magisk-helper"), 0755}, "config/chrootctl/compatibility-manifest.json": {string(compat), 0644}, "config/chrootctl/boot_targets.json": {string(targets), 0644}}
	for rel, v := range files {
		if e := writeFile(out, rel, v.c, v.m); e != nil {
			return e
		}
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
	if opts.ZipPath != "" {
		return Zip(out, opts.ZipPath)
	}
	return nil
}

func Zip(root, path string) error {
	if e := ValidateRendered(root); e != nil {
		return e
	}
	if e := os.MkdirAll(filepath.Dir(path), 0755); e != nil {
		return e
	}
	f, e := os.Create(path)
	if e != nil {
		return e
	}
	zw := zip.NewWriter(f)
	var names []string
	filepath.WalkDir(root, func(p string, d fs.DirEntry, e error) error {
		if e == nil && !d.IsDir() {
			rel, _ := filepath.Rel(root, p)
			names = append(names, filepath.ToSlash(rel))
		}
		return e
	})
	sort.Strings(names)
	epoch := time.Date(1980, 1, 1, 0, 0, 0, 0, time.UTC)
	for _, name := range names {
		p := filepath.Join(root, filepath.FromSlash(name))
		st, e := safeRegular(p)
		if e != nil {
			zw.Close()
			f.Close()
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
			f.Close()
			return e
		}
		src, e := os.Open(p)
		if e != nil {
			zw.Close()
			f.Close()
			return e
		}
		_, e = io.Copy(w, src)
		src.Close()
		if e != nil {
			zw.Close()
			f.Close()
			return e
		}
	}
	if e = zw.Close(); e != nil {
		f.Close()
		return e
	}
	return f.Close()
}
func ValidateRendered(root string) error {
	required := []string{"module.prop", "customize.sh", "post-fs-data.sh", "service.sh", "bin/chrootctl-magisk-helper", "system/bin/chrootctl", "system/bin/chrootctl-magisk-helper", "config/chrootctl/compatibility-manifest.json", "config/chrootctl/boot_targets.json", "runtime/arm64-v8a/runtime-manifest.json", "runtime/arm64-v8a/chrootctl"}
	for _, rel := range required {
		if _, e := safeRegular(filepath.Join(root, filepath.FromSlash(rel))); e != nil {
			return e
		}
	}
	return ValidateRuntime(filepath.Join(root, "runtime", RuntimeABI))
}
