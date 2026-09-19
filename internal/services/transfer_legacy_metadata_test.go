package services

import (
	"strings"
	"testing"
)

func testImportManifest(contract any, includeFeatures bool) map[string]any {
	m := map[string]any{
		"name":      "legacy",
		"path_name": "legacy",
		"distro":    "ubuntu",
		"arch":      "arm64",
		"phase":     "ready",
		"installed": true,
		"metadata":  map[string]any{},
	}
	if contract != nil {
		m["rootfs_metadata_contract"] = contract
	}
	if includeFeatures {
		m["rootfs_metadata_features"] = []any{"uid_gid", "mode_special_bits", "hardlinks", "symlinks"}
	}
	return m
}

func TestLegacyImportManifestRequiresExplicitOptIn(t *testing.T) {
	_, err := validateImportManifest(testImportManifest(nil, false), false)
	if err == nil || !strings.Contains(err.Error(), "--allow-legacy-metadata") {
		t.Fatalf("expected actionable legacy-metadata refusal, got %v", err)
	}
}

func TestLegacyImportManifestExplicitOptInIsMarkedUnverified(t *testing.T) {
	fidelity, err := validateImportManifest(testImportManifest(nil, false), true)
	if err != nil {
		t.Fatalf("legacy opt-in unexpectedly failed: %v", err)
	}
	if fidelity != "legacy_unverified" {
		t.Fatalf("fidelity=%q, want legacy_unverified", fidelity)
	}
}

func TestUnknownMetadataContractCannotBeBypassed(t *testing.T) {
	_, err := validateImportManifest(testImportManifest("future-contract-v99", true), true)
	if err == nil || !strings.Contains(err.Error(), "refusing to bypass") {
		t.Fatalf("expected unknown contract refusal, got %v", err)
	}
}

func TestCHR09MetadataContractRemainsStrictAndProven(t *testing.T) {
	fidelity, err := validateImportManifest(testImportManifest("chrootctl-rootfs-v1", true), false)
	if err != nil {
		t.Fatalf("CHR09 manifest failed: %v", err)
	}
	if fidelity != "proven" {
		t.Fatalf("fidelity=%q, want proven", fidelity)
	}

	_, err = validateImportManifest(testImportManifest("chrootctl-rootfs-v1", false), true)
	if err == nil || !strings.Contains(err.Error(), "metadata feature list") {
		t.Fatalf("legacy flag must not weaken CHR09 feature validation, got %v", err)
	}
}
