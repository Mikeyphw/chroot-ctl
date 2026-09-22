package tmuxruntime

import (
	"context"
	"crypto/sha256"
	"debug/elf"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

const (
	RuntimeABI       = "arm64-v8a"
	ExpectedVersion  = "3.7c"
	DefaultModuleDir = "/data/adb/modules/chrootctl"
	DefaultStateRoot = "/data/adb/chrootctl/runtime/tmux"
	LegacyStateRoot  = "/data/adb/chrootctl/tmux"
	DefaultNamespace = "chrootctl"
)

type Paths struct{ Binary, Manifest, Checksum, StateRoot, SocketRoot, Namespace string }
type Health struct {
	Status       string   `json:"status"`
	Ready        bool     `json:"ready"`
	Version      string   `json:"version,omitempty"`
	SHA256       string   `json:"sha256,omitempty"`
	ABI          string   `json:"abi"`
	StateRoot    string   `json:"stateRoot"`
	SocketRoot   string   `json:"socketRoot"`
	Namespace    string   `json:"namespace"`
	StaleSockets []string `json:"staleSockets"`
	Checks       []string `json:"checks"`
	Error        string   `json:"error,omitempty"`
}
type manifest struct {
	SchemaVersion                                            int `json:"schemaVersion"`
	Component, Version, Platform, ABI, Libc, Linkage, SHA256 string
}

func Resolve() Paths { return ResolveEnviron(os.Environ()) }
func ResolveEnviron(env []string) Paths {
	get := func(k string) string {
		p := k + "="
		for i := len(env) - 1; i >= 0; i-- {
			if strings.HasPrefix(env[i], p) {
				return strings.TrimSpace(strings.TrimPrefix(env[i], p))
			}
		}
		return ""
	}
	module := get("CHROOTCTL_MODULE_DIR")
	if module == "" {
		module = DefaultModuleDir
	}
	binary := get("CHROOTCTL_TMUX_PATH")
	if binary == "" {
		binary = filepath.Join(module, "runtime", RuntimeABI, "tmux")
	}
	state := get("CHROOTCTL_TMUX_STATE_ROOT")
	if state == "" {
		state = DefaultStateRoot
	}
	ns := get("CHROOTCTL_TMUX_NAMESPACE")
	if ns == "" {
		ns = DefaultNamespace
	}
	return Paths{Binary: filepath.Clean(binary), Manifest: filepath.Join(filepath.Dir(binary), "tmux-runtime-manifest.json"), Checksum: filepath.Join(filepath.Dir(binary), "tmux.sha256"), StateRoot: filepath.Clean(state), SocketRoot: filepath.Join(filepath.Clean(state), "sockets"), Namespace: ns}
}
func (p Paths) ValidateAuthority() error {
	if !filepath.IsAbs(p.Binary) || !filepath.IsAbs(p.StateRoot) || !filepath.IsAbs(p.SocketRoot) {
		return errors.New("tmux runtime paths must be absolute")
	}
	if p.Namespace == "" || strings.ContainsAny(p.Namespace, "/\\\x00") || p.Namespace == "." || p.Namespace == ".." {
		return errors.New("invalid tmux namespace")
	}
	if filepath.Clean(p.SocketRoot) != filepath.Join(filepath.Clean(p.StateRoot), "sockets") {
		return errors.New("tmux socket root must be owned by state root")
	}
	return nil
}
func trustedFile(path string, executable bool) error {
	st, e := os.Lstat(path)
	if e != nil {
		return e
	}
	if !st.Mode().IsRegular() || st.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("unsafe runtime file: %s", path)
	}
	if st.Mode().Perm()&0o022 != 0 {
		return fmt.Errorf("runtime file is group/world writable: %s", path)
	}
	if executable && st.Mode().Perm()&0o111 == 0 {
		return fmt.Errorf("runtime file is not executable: %s", path)
	}
	if os.Geteuid() == 0 {
		raw, ok := st.Sys().(*syscall.Stat_t)
		if !ok || raw.Uid != 0 {
			return fmt.Errorf("runtime file is not root-owned: %s", path)
		}
	}
	return nil
}
func EnsureState(p Paths) error {
	if e := p.ValidateAuthority(); e != nil {
		return e
	}
	if filepath.Clean(p.StateRoot) == DefaultStateRoot {
		if _, e := os.Lstat(DefaultStateRoot); errors.Is(e, os.ErrNotExist) {
			if st, le := os.Lstat(LegacyStateRoot); le == nil && st.IsDir() {
				sockets, _ := os.ReadDir(filepath.Join(LegacyStateRoot, "sockets"))
				if len(sockets) != 0 {
					return errors.New("legacy tmux state has live/stale sockets; reconcile or stop sessions before state-root migration")
				}
				if e := os.MkdirAll(filepath.Dir(DefaultStateRoot), 0700); e != nil {
					return e
				}
				if e := os.Rename(LegacyStateRoot, DefaultStateRoot); e != nil {
					return fmt.Errorf("migrate legacy tmux state: %w", e)
				}
			}
		}
	}
	for _, d := range []string{p.StateRoot, p.SocketRoot} {
		if e := os.MkdirAll(d, 0700); e != nil {
			return e
		}
		st, e := os.Lstat(d)
		if e != nil {
			return e
		}
		if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("unsafe tmux state directory: %s", d)
		}
		if e = os.Chmod(d, 0700); e != nil {
			return e
		}
		if os.Geteuid() == 0 {
			raw, ok := st.Sys().(*syscall.Stat_t)
			if !ok || raw.Uid != 0 {
				return fmt.Errorf("tmux state directory is not root-owned: %s", d)
			}
		}
	}
	return nil
}
func digest(path string) (string, error) {
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
func Validate(p Paths) (string, string, error) {
	if e := p.ValidateAuthority(); e != nil {
		return "", "", e
	}
	if e := trustedFile(p.Binary, true); e != nil {
		return "", "", e
	}
	if e := trustedFile(p.Manifest, false); e != nil {
		return "", "", e
	}
	if e := trustedFile(p.Checksum, false); e != nil {
		return "", "", e
	}
	ef, e := elf.Open(p.Binary)
	if e != nil {
		return "", "", fmt.Errorf("tmux ELF: %w", e)
	}
	ok := ef.Class == elf.ELFCLASS64 && ef.Data == elf.ELFDATA2LSB && ef.Machine == elf.EM_AARCH64
	ef.Close()
	if !ok {
		return "", "", errors.New("tmux runtime is not Android ARM64 ELF")
	}
	raw, e := os.ReadFile(p.Manifest)
	if e != nil {
		return "", "", e
	}
	var m manifest
	if e = json.Unmarshal(raw, &m); e != nil {
		return "", "", fmt.Errorf("tmux manifest: %w", e)
	}
	if m.SchemaVersion != 1 || m.Component != "tmux" || m.Version != ExpectedVersion || m.Platform != "android" || m.ABI != RuntimeABI || m.Libc != "bionic-static" || m.Linkage != "static" {
		return "", "", fmt.Errorf("tmux runtime manifest mismatch")
	}
	sum, e := digest(p.Binary)
	if e != nil {
		return "", "", e
	}
	if !strings.EqualFold(sum, m.SHA256) {
		return "", "", errors.New("tmux manifest checksum mismatch")
	}
	check, e := os.ReadFile(p.Checksum)
	if e != nil {
		return "", "", e
	}
	fields := strings.Fields(string(check))
	if len(fields) != 2 || !strings.EqualFold(fields[0], sum) || fields[1] != "tmux" {
		return "", "", errors.New("tmux checksum file mismatch")
	}
	return m.Version, sum, nil
}
func staleSockets(p Paths, now time.Time) []string {
	entries, e := os.ReadDir(p.SocketRoot)
	if e != nil {
		return nil
	}
	out := []string{}
	for _, ent := range entries {
		info, e := ent.Info()
		if e != nil {
			continue
		}
		if info.Mode()&os.ModeSocket == 0 {
			continue
		}
		if now.Sub(info.ModTime()) >= 24*time.Hour {
			out = append(out, ent.Name())
		}
	}
	return out
}
func Inspect(ctx context.Context) Health { return InspectPaths(ctx, Resolve()) }
func InspectPaths(_ context.Context, p Paths) Health {
	h := Health{Status: "blocked", ABI: RuntimeABI, StateRoot: p.StateRoot, SocketRoot: p.SocketRoot, Namespace: p.Namespace, StaleSockets: []string{}, Checks: []string{}}
	if e := EnsureState(p); e != nil {
		h.Error = e.Error()
		return h
	}
	h.Checks = append(h.Checks, "state_permissions")
	v, sum, e := Validate(p)
	if e != nil {
		h.Error = e.Error()
		return h
	}
	h.Version = v
	h.SHA256 = sum
	h.Checks = append(h.Checks, "binary_trust", "elf_arm64", "version", "checksum")
	h.StaleSockets = staleSockets(p, time.Now())
	if len(h.StaleSockets) > 0 {
		h.Status = "degraded"
		h.Error = "stale tmux sockets detected"
		return h
	}
	h.Ready = true
	h.Status = "ready"
	return h
}
