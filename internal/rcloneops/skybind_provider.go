package rcloneops

// The Skybind provider is an *explicit*, root-local transport choice. It uses
// Skybind's installed public wrapper and private configuration; it is not the
// managed-feature API and it does not grant an R1 read token. Nothing here
// rewrites or imports credentials into Chrootctl's own configuration.

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

const (
	skybindModuleDir             = "/data/adb/modules/skybind"
	skybindConfigDir             = "/data/adb/skybind/config"
	DefaultProviderSelectionPath = DefaultStateRoot + "/rclone/provider"
)

type skybindLayout struct {
	moduleDir string
	configDir string
}

type skybindFileRecord struct {
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

type skybindInstalledManifest struct {
	SchemaVersion int                          `json:"schema_version"`
	Product       string                       `json:"product"`
	Qualification string                       `json:"qualification"`
	ProvenanceSHA string                       `json:"runtime_provenance_sha256"`
	Files         map[string]skybindFileRecord `json:"files"`
}

type skybindRuntimeProvenance struct {
	SchemaVersion int                          `json:"schema_version"`
	Product       string                       `json:"product"`
	Arch          string                       `json:"arch"`
	EnginePath    string                       `json:"engine_path"`
	Files         map[string]skybindFileRecord `json:"files"`
}

// SelectedProvider reports an explicitly configured transport selector without
// probing a remote or executing an external binary. Empty means legacy mode.
func SelectedProvider() (string, error) {
	return selectedRcloneProvider(func(key string) string { return strings.TrimSpace(os.Getenv(key)) })
}

// A root-private provider selection survives interactive sessions and is also
// seen by Chrootctl's WebUI/service process. A per-process environment choice
// overrides it. Nothing is auto-selected merely because Skybind is installed.
func selectedRcloneProvider(lookup func(string) string) (string, error) {
	if p := lookup("CHROOTCTL_RCLONE_PROVIDER"); p != "" {
		return p, nil
	}
	if os.Geteuid() != 0 {
		return "", nil
	}
	p, err := readRcloneProviderSelection(DefaultProviderSelectionPath, 0)
	if os.IsNotExist(err) {
		return "", nil
	}
	return p, err
}

func readRcloneProviderSelection(path string, owner uint32) (string, error) {
	st, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if !skybindSafeFile(st, owner) || st.Mode().Perm()&0o077 != 0 || st.Size() > 32 || st.Size() < 1 {
		return "", errors.New("untrusted rclone provider selection")
	}
	if err := skybindSafeDirectory(filepath.Dir(path), owner); err != nil {
		return "", errors.New("untrusted rclone provider selection directory")
	}
	body, err := skybindReadTrusted(path, owner, 32)
	if err != nil {
		return "", err
	}
	choice := strings.TrimSuffix(string(body), "\n")
	if choice != "skybind" && choice != "chrootctl" {
		return "", errors.New("unknown configured rclone provider")
	}
	return choice, nil
}

// skybindRuntimeAt is split from production dispatch solely to run the exact
// validation on throwaway, non-root CI fixtures. Production never accepts a
// module path or owner from an environment variable or IPC request.
func skybindRuntimeAt(layout skybindLayout, owner uint32) (Runtime, error) {
	const (
		alias  = "system/bin/skybind-rclone"
		engine = "system/bin/skybind-rclone-engine"
		prov   = "runtime.provenance.json"
	)
	if err := skybindSafeDirectory(filepath.Dir(layout.moduleDir), owner); err != nil {
		return Runtime{}, fmt.Errorf("skybind module parent is not trusted: %w", err)
	}
	if err := skybindSafeDirectory(layout.moduleDir, owner); err != nil {
		return Runtime{}, fmt.Errorf("skybind module is not trusted: %w", err)
	}
	for _, part := range []string{"system", "system/bin"} {
		if err := skybindSafeDirectory(filepath.Join(layout.moduleDir, part), owner); err != nil {
			return Runtime{}, fmt.Errorf("skybind runtime directory is not trusted: %w", err)
		}
	}
	moduleProp := filepath.Join(layout.moduleDir, "module.prop")
	prop, err := skybindReadTrusted(moduleProp, owner, 32<<10)
	if err != nil || !strings.HasPrefix(string(prop), "id=skybind\n") {
		return Runtime{}, errors.New("skybind installed module identity not trusted")
	}
	manifestRaw, err := skybindReadTrusted(filepath.Join(layout.moduleDir, "skybind.manifest.json"), owner, 2<<20)
	if err != nil {
		return Runtime{}, fmt.Errorf("skybind installed manifest unavailable: %w", err)
	}
	var manifest skybindInstalledManifest
	if err := json.Unmarshal(manifestRaw, &manifest); err != nil || manifest.SchemaVersion != 1 || manifest.Product != "skybind" || manifest.Files == nil || !skybindValidDigest(manifest.ProvenanceSHA) {
		return Runtime{}, errors.New("skybind installed manifest invalid")
	}
	provenanceRaw, err := skybindReadTrusted(filepath.Join(layout.moduleDir, prov), owner, 2<<20)
	if err != nil || skybindDigest(provenanceRaw) != manifest.ProvenanceSHA {
		return Runtime{}, errors.New("skybind runtime provenance differs from installed manifest")
	}
	var provenance skybindRuntimeProvenance
	if err := json.Unmarshal(provenanceRaw, &provenance); err != nil || provenance.SchemaVersion != 1 || provenance.Product != "Skybind" || provenance.Arch != "arm64" || provenance.EnginePath != engine {
		return Runtime{}, errors.New("skybind native-rclone runtime provenance invalid")
	}
	files := []string{alias, engine, "system/bin/rclone", prov}
	for _, rel := range files {
		path := filepath.Join(layout.moduleDir, rel)
		sizeLimit := int64(256 << 20)
		if rel == prov {
			sizeLimit = 2 << 20
		}
		if rel == alias || rel == "system/bin/rclone" {
			sizeLimit = 128 << 10
		}
		digest, size, e := skybindHashTrusted(path, owner, sizeLimit)
		if e != nil || !skybindRecordMatches(manifest.Files[rel], digest, size) {
			return Runtime{}, fmt.Errorf("skybind installed member not verified: %s", rel)
		}
		if rel != prov && !skybindRecordMatches(provenance.Files[rel], digest, size) {
			return Runtime{}, fmt.Errorf("skybind runtime provenance member not verified: %s", rel)
		}
	}
	// Public alias and PATH wrapper must be identical. This binds both names
	// to one provenance-checked executable rather than a mutable replacement.
	if manifest.Files[alias] != manifest.Files["system/bin/rclone"] {
		return Runtime{}, errors.New("skybind public wrapper and alias differ")
	}
	wrapper := filepath.Join(layout.moduleDir, alias)
	st, err := os.Lstat(wrapper)
	if err != nil || st.Mode().Perm()&0o100 == 0 {
		return Runtime{}, errors.New("skybind public wrapper not executable")
	}
	enginePath := filepath.Join(layout.moduleDir, engine)
	st, err = os.Lstat(enginePath)
	if err != nil || st.Mode().Perm()&0o100 == 0 || !skybindIsARM64ELF(enginePath, owner) {
		return Runtime{}, errors.New("skybind native engine not a trusted executable ARM64 ELF")
	}
	// A private root-owned credential file is an explicit dependency. There
	// is no fallback to an empty or Chrootctl-local rclone.conf.
	if err := skybindSafeDirectory(filepath.Dir(layout.configDir), owner); err != nil {
		return Runtime{}, fmt.Errorf("skybind configuration parent is not trusted: %w", err)
	}
	if err := skybindSafeDirectory(layout.configDir, owner); err != nil {
		return Runtime{}, fmt.Errorf("skybind credential directory not trusted: %w", err)
	}
	config := filepath.Join(layout.configDir, "rclone.conf")
	st, err = os.Lstat(config)
	if err != nil || !skybindSafeFile(st, owner) || st.Mode().Perm()&0o077 != 0 || st.Size() == 0 {
		return Runtime{}, errors.New("skybind private rclone configuration unavailable or unsafe")
	}
	return Runtime{Executable: wrapper, Config: config, Provider: "skybind"}, nil
}

// Reject a provenance-matching but non-Android binary before handing it root
// execution. The installed manifest hash is still verified separately above.
func skybindIsARM64ELF(path string, owner uint32) bool {
	st, err := os.Lstat(path)
	if err != nil || !skybindSafeFile(st, owner) {
		return false
	}
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	defer f.Close()
	var hdr [20]byte
	if _, err = io.ReadFull(f, hdr[:]); err != nil {
		return false
	}
	return string(hdr[:4]) == "\x7fELF" && hdr[4] == 2 && hdr[5] == 1 && hdr[6] == 1 && hdr[18] == 0xb7 && hdr[19] == 0
}

func skybindValidDigest(s string) bool {
	if len(s) != 64 {
		return false
	}
	for _, c := range s {
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}

func skybindDigest(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

func skybindRecordMatches(rec skybindFileRecord, hash string, size int64) bool {
	return skybindValidDigest(rec.SHA256) && rec.SHA256 == hash && rec.Size == size && size > 0
}

func skybindSafeFile(st os.FileInfo, owner uint32) bool {
	if st == nil || !st.Mode().IsRegular() || st.Mode()&os.ModeSymlink != 0 || st.Mode().Perm()&0o022 != 0 {
		return false
	}
	v, ok := st.Sys().(*syscall.Stat_t)
	return ok && v.Uid == owner && v.Nlink == 1
}

func skybindSafeDirectory(path string, owner uint32) error {
	st, err := os.Lstat(path)
	if err != nil || !st.IsDir() || st.Mode()&os.ModeSymlink != 0 || st.Mode().Perm()&0o022 != 0 {
		return errors.New("unsafe directory")
	}
	v, ok := st.Sys().(*syscall.Stat_t)
	if !ok || v.Uid != owner {
		return errors.New("unexpected directory owner")
	}
	return nil
}

func skybindReadTrusted(path string, owner uint32, max int64) ([]byte, error) {
	st, err := os.Lstat(path)
	if err != nil || !skybindSafeFile(st, owner) || st.Size() <= 0 || st.Size() > max {
		return nil, errors.New("unsafe installed file")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !os.SameFile(st, opened) {
		return nil, errors.New("installed file changed during open")
	}
	body, err := io.ReadAll(io.LimitReader(f, max+1))
	if err != nil || int64(len(body)) != opened.Size() || int64(len(body)) > max {
		return nil, errors.New("installed file read failed")
	}
	return body, nil
}

func skybindHashTrusted(path string, owner uint32, max int64) (string, int64, error) {
	st, err := os.Lstat(path)
	if err != nil || !skybindSafeFile(st, owner) || st.Size() <= 0 || st.Size() > max {
		return "", 0, errors.New("unsafe installed member")
	}
	f, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !os.SameFile(st, opened) {
		return "", 0, errors.New("installed member changed")
	}
	h := sha256.New()
	n, err := io.Copy(h, io.LimitReader(f, max+1))
	if err != nil || n != opened.Size() || n > max {
		return "", 0, errors.New("installed member incomplete")
	}
	return hex.EncodeToString(h.Sum(nil)), n, nil
}
