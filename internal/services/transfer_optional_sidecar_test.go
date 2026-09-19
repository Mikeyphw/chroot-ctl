package services

import (
	"context"
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestArchiveChecksumMissingSidecarComputesDigestWithoutClaimingExportVerification(t *testing.T) {
	dir := t.TempDir()
	archive := filepath.Join(dir, "rootfs.tar.zst")
	body := []byte("already-exported-chroot")
	if err := os.WriteFile(archive, body, 0o600); err != nil {
		t.Fatal(err)
	}

	sum, sidecar, verified, err := requireArchiveChecksum(context.Background(), TransferControl{}, archive)
	if err != nil {
		t.Fatalf("missing sidecar must be accepted: %v", err)
	}
	want := fmt.Sprintf("%x", sha256.Sum256(body))
	if sum == nil || *sum != want {
		t.Fatalf("computed checksum = %v, want %s", sum, want)
	}
	if sidecar != nil {
		t.Fatalf("missing sidecar must not invent checksum_path: %v", *sidecar)
	}
	if verified == nil || *verified {
		t.Fatalf("missing original sidecar must be explicitly unverified: %v", verified)
	}
	if got := checksumIntegritySource(verified); got != "computed_on_import" {
		t.Fatalf("integrity source = %q", got)
	}
}

func TestArchiveChecksumExistingValidSidecarRemainsVerified(t *testing.T) {
	dir := t.TempDir()
	archive := filepath.Join(dir, "rootfs.tar.zst")
	body := []byte("verified-export")
	if err := os.WriteFile(archive, body, 0o600); err != nil {
		t.Fatal(err)
	}
	want := fmt.Sprintf("%x", sha256.Sum256(body))
	if err := os.WriteFile(archive+".sha256", []byte(want+"  "+filepath.Base(archive)+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	sum, sidecar, verified, err := requireArchiveChecksum(context.Background(), TransferControl{}, archive)
	if err != nil {
		t.Fatal(err)
	}
	if sum == nil || *sum != want || sidecar == nil || verified == nil || !*verified {
		t.Fatalf("valid sidecar not verified: sum=%v sidecar=%v verified=%v", sum, sidecar, verified)
	}
	if got := checksumIntegritySource(verified); got != "export_sidecar_verified" {
		t.Fatalf("integrity source = %q", got)
	}
}

func TestArchiveChecksumExistingMismatchStillFailsClosed(t *testing.T) {
	dir := t.TempDir()
	archive := filepath.Join(dir, "rootfs.tar.zst")
	if err := os.WriteFile(archive, []byte("actual"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(archive+".sha256", []byte(strings.Repeat("0", 64)+"  "+filepath.Base(archive)+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := requireArchiveChecksum(context.Background(), TransferControl{}, archive); err == nil || !strings.Contains(err.Error(), "verification failed") {
		t.Fatalf("existing mismatched sidecar must fail closed, got %v", err)
	}
}

func TestArchiveChecksumMalformedExistingSidecarStillFailsClosed(t *testing.T) {
	dir := t.TempDir()
	archive := filepath.Join(dir, "rootfs.tar.zst")
	if err := os.WriteFile(archive, []byte("actual"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(archive+".sha256", []byte("not-a-sha256\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := requireArchiveChecksum(context.Background(), TransferControl{}, archive); err == nil || !strings.Contains(err.Error(), "malformed") {
		t.Fatalf("malformed existing sidecar must fail closed, got %v", err)
	}
}
