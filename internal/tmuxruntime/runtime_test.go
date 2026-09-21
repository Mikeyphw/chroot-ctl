package tmuxruntime

import (
	"context"
	"debug/elf"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func fakeELF(t *testing.T, p string, m elf.Machine, mode os.FileMode) string {
	t.Helper()
	b := make([]byte, 64)
	copy(b, []byte{0x7f, 'E', 'L', 'F', 2, 1, 1})
	binary.LittleEndian.PutUint16(b[16:], uint16(elf.ET_DYN))
	binary.LittleEndian.PutUint32(b[20:], 1)
	binary.LittleEndian.PutUint16(b[18:], uint16(m))
	if e := os.WriteFile(p, b, mode); e != nil {
		t.Fatal(e)
	}
	return p
}
func fixture(t *testing.T) Paths {
	t.Helper()
	r := t.TempDir()
	d := filepath.Join(r, "runtime", "arm64-v8a")
	os.MkdirAll(d, 0700)
	p := Paths{Binary: filepath.Join(d, "tmux"), Manifest: filepath.Join(d, "tmux-runtime-manifest.json"), Checksum: filepath.Join(d, "tmux.sha256"), StateRoot: filepath.Join(r, "state"), SocketRoot: filepath.Join(r, "state", "sockets"), Namespace: "chrootctl"}
	fakeELF(t, p.Binary, elf.EM_AARCH64, 0755)
	sum, _ := digest(p.Binary)
	m := map[string]any{"schemaVersion": 1, "component": "tmux", "version": ExpectedVersion, "platform": "android", "abi": RuntimeABI, "libc": "bionic-static", "linkage": "static", "sha256": sum}
	raw, _ := json.Marshal(m)
	os.WriteFile(p.Manifest, raw, 0644)
	os.WriteFile(p.Checksum, []byte(fmt.Sprintf("%s  tmux\n", sum)), 0644)
	return p
}
func TestResolveNeverUsesPATH(t *testing.T) {
	p := ResolveEnviron([]string{"PATH=/evil", "CHROOTCTL_MODULE_DIR=/module"})
	if p.Binary != "/module/runtime/arm64-v8a/tmux" {
		t.Fatal(p.Binary)
	}
}
func TestAuthorityAndPermissions(t *testing.T) {
	p := fixture(t)
	if e := EnsureState(p); e != nil {
		t.Fatal(e)
	}
	for _, d := range []string{p.StateRoot, p.SocketRoot} {
		st, _ := os.Stat(d)
		if st.Mode().Perm() != 0700 {
			t.Fatalf("%s mode %o", d, st.Mode().Perm())
		}
	}
}
func TestHealthyRuntime(t *testing.T) {
	p := fixture(t)
	h := InspectPaths(context.Background(), p)
	if !h.Ready || h.Status != "ready" || h.Version != ExpectedVersion {
		t.Fatalf("%+v", h)
	}
}
func TestMissingRuntime(t *testing.T) {
	p := fixture(t)
	os.Remove(p.Binary)
	if h := InspectPaths(context.Background(), p); h.Ready || h.Error == "" {
		t.Fatalf("%+v", h)
	}
}
func TestCorruptRuntime(t *testing.T) {
	p := fixture(t)
	os.WriteFile(p.Binary, []byte("bad"), 0755)
	if h := InspectPaths(context.Background(), p); h.Ready || !strings.Contains(h.Error, "ELF") {
		t.Fatalf("%+v", h)
	}
}
func TestWrongArch(t *testing.T) {
	p := fixture(t)
	fakeELF(t, p.Binary, elf.EM_X86_64, 0755)
	sum, _ := digest(p.Binary)
	raw, _ := os.ReadFile(p.Manifest)
	var m map[string]any
	json.Unmarshal(raw, &m)
	m["sha256"] = sum
	raw, _ = json.Marshal(m)
	os.WriteFile(p.Manifest, raw, 0644)
	os.WriteFile(p.Checksum, []byte(sum+"  tmux\n"), 0644)
	if h := InspectPaths(context.Background(), p); h.Ready || !strings.Contains(h.Error, "ARM64") {
		t.Fatalf("%+v", h)
	}
}
func TestNotExecutable(t *testing.T) {
	p := fixture(t)
	os.Chmod(p.Binary, 0644)
	if h := InspectPaths(context.Background(), p); h.Ready || !strings.Contains(h.Error, "not executable") {
		t.Fatalf("%+v", h)
	}
}
func TestVersionMismatch(t *testing.T) {
	p := fixture(t)
	raw, _ := os.ReadFile(p.Manifest)
	var m map[string]any
	json.Unmarshal(raw, &m)
	m["version"] = "0.0"
	raw, _ = json.Marshal(m)
	os.WriteFile(p.Manifest, raw, 0644)
	if h := InspectPaths(context.Background(), p); h.Ready || !strings.Contains(h.Error, "manifest mismatch") {
		t.Fatalf("%+v", h)
	}
}
func TestChecksumMismatch(t *testing.T) {
	p := fixture(t)
	os.WriteFile(p.Checksum, []byte(strings.Repeat("0", 64)+"  tmux\n"), 0644)
	if h := InspectPaths(context.Background(), p); h.Ready || !strings.Contains(h.Error, "checksum") {
		t.Fatalf("%+v", h)
	}
}

func TestStaleSocketDegradesHealth(t *testing.T) {
	p := fixture(t)
	// AF_UNIX sockaddr paths are short on Android. Devtool can provide a very
	// long TMPDIR and the repository path itself can also exceed sockaddr_un.
	// Use a deliberately short Termux-private root, never /tmp.
	shortBase := os.Getenv("PREFIX")
	if shortBase == "" {
		shortBase = os.TempDir()
	}
	shortBase = filepath.Join(shortBase, "tmp")
	if err := os.MkdirAll(shortBase, 0700); err != nil {
		t.Fatal(err)
	}
	short, err := os.MkdirTemp(shortBase, "t2-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(short)
	p.StateRoot = filepath.Join(short, "state")
	p.SocketRoot = filepath.Join(p.StateRoot, "sockets")
	if err := EnsureState(p); err != nil {
		t.Fatal(err)
	}
	sock := filepath.Join(p.SocketRoot, "old.sock")
	// Linux/Android sockaddr_un.sun_path is 108 bytes including NUL. Keep
	// headroom and fail with a useful diagnostic before net.Listen does.
	const maxUnixSocketPath = 107
	if len([]byte(sock)) > maxUnixSocketPath {
		t.Fatalf("test socket path too long: %d > %d: %s", len([]byte(sock)), maxUnixSocketPath, sock)
	}
	l, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	old := time.Now().Add(-25 * time.Hour)
	if err := os.Chtimes(sock, old, old); err != nil {
		t.Fatal(err)
	}
	h := InspectPaths(context.Background(), p)
	if h.Ready || h.Status != "degraded" || len(h.StaleSockets) != 1 || h.StaleSockets[0] != "old.sock" {
		t.Fatalf("%+v", h)
	}
}

func TestUnsafeStateSymlinkRejected(t *testing.T) {
	p := fixture(t)
	target := filepath.Join(t.TempDir(), "target")
	if err := os.Mkdir(target, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, p.StateRoot); err != nil {
		t.Fatal(err)
	}
	if err := EnsureState(p); err == nil {
		t.Fatal("expected symlink rejection")
	}
}
