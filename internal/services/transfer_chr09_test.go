package services

import (
	"archive/tar"
	"context"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestCHR09TransferImportRestoresOwnershipSpecialBitsAndFIFO(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("rootfs metadata fixture requires root")
	}
	root := t.TempDir()
	tarPath := filepath.Join(root, "archive.tar")
	dest := filepath.Join(root, "dest")
	f, err := os.Create(tarPath)
	if err != nil {
		t.Fatal(err)
	}
	tw := tar.NewWriter(f)
	headers := []tar.Header{
		{Name: "work", Typeflag: tar.TypeDir, Mode: 0o755, Uid: 0, Gid: 0},
		{Name: "work/tool", Typeflag: tar.TypeReg, Mode: 0o4755, Uid: 1234, Gid: 2345, Size: 4},
		{Name: "work/pipe", Typeflag: tar.TypeFifo, Mode: 0o640, Uid: 1234, Gid: 2345},
	}
	for i := range headers {
		if err := tw.WriteHeader(&headers[i]); err != nil {
			t.Fatal(err)
		}
		if headers[i].Name == "work/tool" {
			if _, err := tw.Write([]byte("data")); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	if err := extractRootFromTar(context.Background(), TransferControl{}, tarPath, dest, "work"); err != nil {
		t.Fatal(err)
	}
	st, err := os.Stat(filepath.Join(dest, "tool"))
	if err != nil {
		t.Fatal(err)
	}
	ss := st.Sys().(*syscall.Stat_t)
	if ss.Uid != 1234 || ss.Gid != 2345 {
		t.Fatalf("ownership=%d:%d", ss.Uid, ss.Gid)
	}
	if st.Mode()&os.ModeSetuid == 0 {
		t.Fatalf("setuid lost: %v", st.Mode())
	}
	ps, err := os.Lstat(filepath.Join(dest, "pipe"))
	if err != nil {
		t.Fatal(err)
	}
	if ps.Mode()&os.ModeNamedPipe == 0 {
		t.Fatalf("fifo=%v", ps.Mode())
	}
}
