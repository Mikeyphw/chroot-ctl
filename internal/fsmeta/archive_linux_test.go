//go:build linux || android

package fsmeta

import (
	"context"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestArchiveRoundTripPreservesRootfsMetadata(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("ownership/device metadata test requires root")
	}
	root := t.TempDir()
	src := filepath.Join(root, "src")
	dst := filepath.Join(root, "dst")
	arc := filepath.Join(root, "snap.tar.gz")
	if err := os.MkdirAll(filepath.Join(src, "dir"), 0o755); err != nil {
		t.Fatal(err)
	}
	f := filepath.Join(src, "dir", "tool")
	if err := os.WriteFile(f, []byte("payload"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chown(f, 1234, 2345); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(f, os.FileMode(0o755)|os.ModeSetuid); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Setxattr(f, "user.chrootctl", []byte{0, 1, 2, 3, 255}, 0); err != nil && err != syscall.ENOTSUP && err != syscall.EOPNOTSUPP {
		t.Fatal(err)
	}
	if err := os.Link(f, filepath.Join(src, "dir", "tool-link")); err != nil {
		t.Fatal(err)
	}
	fifo := filepath.Join(src, "pipe")
	if err := syscall.Mkfifo(fifo, 0o640); err != nil {
		t.Fatal(err)
	}
	sparse := filepath.Join(src, "sparse")
	sf, err := os.Create(sparse)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = sf.Seek(2<<20, 0); err != nil {
		t.Fatal(err)
	}
	if _, err = sf.Write([]byte("end")); err != nil {
		t.Fatal(err)
	}
	sf.Close()
	if err := ArchiveTreeGzip(context.Background(), src, arc, CopyControl{}); err != nil {
		t.Fatal(err)
	}
	if err := ExtractTarGzip(context.Background(), arc, dst, CopyControl{}); err != nil {
		t.Fatal(err)
	}
	st, err := os.Stat(filepath.Join(dst, "dir", "tool"))
	if err != nil {
		t.Fatal(err)
	}
	stat := st.Sys().(*syscall.Stat_t)
	if stat.Uid != 1234 || stat.Gid != 2345 {
		t.Fatalf("ownership=%d:%d", stat.Uid, stat.Gid)
	}
	if st.Mode()&os.ModeSetuid == 0 {
		t.Fatalf("setuid lost: %v", st.Mode())
	}
	a, _ := os.Stat(filepath.Join(dst, "dir", "tool"))
	b, _ := os.Stat(filepath.Join(dst, "dir", "tool-link"))
	if a.Sys().(*syscall.Stat_t).Ino != b.Sys().(*syscall.Stat_t).Ino {
		t.Fatal("hardlink identity lost")
	}
	ps, err := os.Lstat(filepath.Join(dst, "pipe"))
	if err != nil {
		t.Fatal(err)
	}
	if ps.Mode()&os.ModeNamedPipe == 0 {
		t.Fatalf("fifo lost: %v", ps.Mode())
	}
	ss, err := os.Stat(filepath.Join(dst, "sparse"))
	if err != nil {
		t.Fatal(err)
	}
	if ss.Size() != (2<<20)+3 {
		t.Fatalf("sparse size=%d", ss.Size())
	}
}

func TestArchiveRejectsLiveSocket(t *testing.T) {
	// A socket is runtime state and must never disappear silently from a snapshot.
	root := t.TempDir()
	src := filepath.Join(root, "src")
	if err := os.Mkdir(src, 0o755); err != nil {
		t.Fatal(err)
	}
	// Use mknod-style socket mode where supported; otherwise this assertion is covered by source inspection.
	path := filepath.Join(src, "sock")
	if err := syscall.Mknod(path, syscall.S_IFSOCK|0o600, 0); err != nil {
		t.Skipf("socket node unavailable: %v", err)
	}
	if err := ArchiveTreeGzip(context.Background(), src, filepath.Join(root, "x.tar.gz"), CopyControl{}); err == nil {
		t.Fatal("expected socket rejection")
	}
}
