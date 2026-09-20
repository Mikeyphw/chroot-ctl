package services

import (
	"archive/tar"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeLayoutFixture(t *testing.T, manifestFirst bool, extraTopLevel string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "fixture.tar")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	tw := tar.NewWriter(f)
	uid, gid := os.Geteuid(), os.Getegid()
	manifestBytes, err := json.Marshal(map[string]any{"path_name": "androidos", "name": "androidos"})
	if err != nil {
		t.Fatal(err)
	}
	writeManifest := func() {
		t.Helper()
		if err := tw.WriteHeader(&tar.Header{Name: exportManifestMember, Typeflag: tar.TypeReg, Mode: 0o600, Uid: uid, Gid: gid, Size: int64(len(manifestBytes))}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write(manifestBytes); err != nil {
			t.Fatal(err)
		}
	}
	if manifestFirst {
		writeManifest()
	}
	if err := tw.WriteHeader(&tar.Header{Name: "androidos", Typeflag: tar.TypeDir, Mode: 0o755, Uid: uid, Gid: gid}); err != nil {
		t.Fatal(err)
	}
	payload := []byte("hello")
	if err := tw.WriteHeader(&tar.Header{Name: "androidos/etc/example", Typeflag: tar.TypeReg, Mode: 0o644, Uid: uid, Gid: gid, Size: int64(len(payload))}); err != nil {
		t.Fatal(err)
	}
	if _, err := tw.Write(payload); err != nil {
		t.Fatal(err)
	}
	if extraTopLevel != "" {
		bad := []byte("unexpected")
		if err := tw.WriteHeader(&tar.Header{Name: extraTopLevel, Typeflag: tar.TypeReg, Mode: 0o600, Uid: uid, Gid: gid, Size: int64(len(bad))}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write(bad); err != nil {
			t.Fatal(err)
		}
	}
	if !manifestFirst {
		writeManifest()
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestInspectTarAcceptsExportManifestBeforeOrAfterRootfs(t *testing.T) {
	for _, first := range []bool{true, false} {
		t.Run(map[bool]string{true: "manifest-first", false: "manifest-last"}[first], func(t *testing.T) {
			path := writeLayoutFixture(t, first, "")
			manifest, _, err := inspectTar(context.Background(), TransferControl{}, path)
			if err != nil {
				t.Fatal(err)
			}
			if got := manifestText(manifest, "path_name"); got != "androidos" {
				t.Fatalf("path_name=%q", got)
			}
		})
	}
}

func TestInspectTarRejectsUnexpectedTopLevelMemberDuringPreflight(t *testing.T) {
	path := writeLayoutFixture(t, false, "unexpected.txt")
	_, _, err := inspectTar(context.Background(), TransferControl{}, path)
	if err == nil || !strings.Contains(err.Error(), "unexpected archive member outside root androidos: unexpected.txt") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestExtractRootFromTarConsumesManifestAtEndWithoutExtractingIt(t *testing.T) {
	path := writeLayoutFixture(t, false, "")
	dest := t.TempDir()
	if err := extractRootFromTar(context.Background(), TransferControl{}, path, dest, "androidos"); err != nil {
		t.Fatal(err)
	}
	if got, err := os.ReadFile(filepath.Join(dest, "etc", "example")); err != nil || string(got) != "hello" {
		t.Fatalf("payload=%q err=%v", got, err)
	}
	if _, err := os.Stat(filepath.Join(dest, exportManifestMember)); !os.IsNotExist(err) {
		t.Fatalf("control manifest leaked into rootfs: %v", err)
	}
}

func writeTopologyFixture(t *testing.T, headers []*tar.Header, payloads map[string][]byte) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "topology.tar")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	tw := tar.NewWriter(f)
	for _, h := range headers {
		if err := tw.WriteHeader(h); err != nil {
			t.Fatal(err)
		}
		if payload := payloads[h.Name]; len(payload) != 0 {
			if _, err := tw.Write(payload); err != nil {
				t.Fatal(err)
			}
		}
	}
	manifestBytes, _ := json.Marshal(map[string]any{"path_name": "androidos", "name": "androidos"})
	if err := tw.WriteHeader(&tar.Header{Name: exportManifestMember, Typeflag: tar.TypeReg, Mode: 0o600, Size: int64(len(manifestBytes))}); err != nil {
		t.Fatal(err)
	}
	if _, err := tw.Write(manifestBytes); err != nil {
		t.Fatal(err)
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestInspectTarPreflightRejectsHardlinkTargetBeforeExtraction(t *testing.T) {
	path := writeTopologyFixture(t, []*tar.Header{
		{Name: "androidos", Typeflag: tar.TypeDir, Mode: 0o755},
		{Name: "androidos/etc/link", Typeflag: tar.TypeLink, Mode: 0o644, Linkname: "androidos/etc/missing"},
	}, nil)
	_, _, err := inspectTar(context.Background(), TransferControl{}, path)
	if err == nil || !strings.Contains(err.Error(), "hardlink target is not a previously declared regular file") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestInspectTarPreflightRejectsMemberBelowSymlinkBeforeExtraction(t *testing.T) {
	payload := []byte("late")
	path := writeTopologyFixture(t, []*tar.Header{
		{Name: "androidos", Typeflag: tar.TypeDir, Mode: 0o755},
		{Name: "androidos/usr", Typeflag: tar.TypeSymlink, Mode: 0o777, Linkname: "real-usr"},
		{Name: "androidos/usr/bin/tool", Typeflag: tar.TypeReg, Mode: 0o755, Size: int64(len(payload))},
	}, map[string][]byte{"androidos/usr/bin/tool": payload})
	_, _, err := inspectTar(context.Background(), TransferControl{}, path)
	if err == nil || !strings.Contains(err.Error(), "has non-directory parent usr") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestInspectTarPreflightRejectsNonDirectoryArchiveRoot(t *testing.T) {
	payload := []byte("not-a-root-dir")
	path := writeTopologyFixture(t, []*tar.Header{
		{Name: "androidos", Typeflag: tar.TypeReg, Mode: 0o644, Size: int64(len(payload))},
	}, map[string][]byte{"androidos": payload})
	_, _, err := inspectTar(context.Background(), TransferControl{}, path)
	if err == nil || !strings.Contains(err.Error(), "archive root androidos must be a directory") {
		t.Fatalf("unexpected error: %v", err)
	}
}
