package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCC10ReconciliationDistinguishesHostedCandidateFromDevice(t *testing.T) {
	dir := t.TempDir()
	artifacts := make([]map[string]any, 0)
	manifests := map[string]string{}
	for _, ed := range []string{"standard", "rclone"} {
		b := []byte("fake-hosted-" + ed)
		n := "chrootctl-" + ed + "-arm64.zip"
		if err := os.WriteFile(filepath.Join(dir, n), b, 0600); err != nil {
			t.Fatal(err)
		}
		digest := sha256.Sum256(b)
		manifest := strings.Repeat("a", 64)
		if ed == "rclone" {
			manifest = strings.Repeat("b", 64)
		}
		manifests[ed] = manifest
		artifacts = append(artifacts, map[string]any{"edition": ed, "filename": n, "sha256": hex.EncodeToString(digest[:]), "runtimeManifestSha256": manifest})
	}
	source := strings.Repeat("1", 40)
	devtool := strings.Repeat("2", 40)
	index := map[string]any{"schemaVersion": 1, "androidApi": 26, "sourceCommit": source, "devtoolCommit": devtool, "qualification": "HOSTED_CANDIDATE_NOT_DEVICE_QUALIFIED", "artifacts": artifacts}
	raw, _ := json.Marshal(index)
	if err := os.WriteFile(filepath.Join(dir, "release-evidence.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	result, err := reconcile(dir, nil)
	if err != nil || !result.AllHostedArtifactsVerified || result.Qualification != "NOT_DEVICE_QUALIFIED" || len(result.DeviceSnapshotsMatched) != 0 {
		t.Fatalf("hosted-only classification wrong: %#v %v", result, err)
	}
	proof := map[string]any{"schemaVersion": 1, "probe": "chrootctl-cc09-installed-v1", "mode": "device", "edition": "standard", "androidApi": 26, "sourceCommit": source, "devtoolCommit": devtool, "runtimeManifestSha256": manifests["standard"], "runtimeSHA256": strings.Repeat("c", 64), "bootId": "12345678-1234-1234-1234-123456789abc", "bootCompleted": "1", "selinux": "Enforcing", "uid": "0", "assessment": "INSTALLED_SNAPSHOT_UNATTESTED", "skybindR1": "NOT_TESTED", "skybindR3R4": "NOT_QUALIFIED"}
	path := filepath.Join(t.TempDir(), "standard.json")
	put := func() {
		v, _ := json.Marshal(proof)
		if err := os.WriteFile(path, v, 0600); err != nil {
			t.Fatal(err)
		}
	}
	put()
	matched, err := reconcile(dir, map[string]string{"standard": path})
	if err != nil || len(matched.DeviceSnapshotsMatched) != 1 || matched.Qualification != "NOT_DEVICE_QUALIFIED" {
		t.Fatalf("device snapshot made false release claim: %#v %v", matched, err)
	}
	proof["mode"] = "fixture"
	put()
	if _, err := reconcile(dir, map[string]string{"standard": path}); err == nil {
		t.Fatal("fixture treated as real device")
	}
	proof["mode"] = "device"
	proof["runtimeManifestSha256"] = strings.Repeat("d", 64)
	put()
	if _, err := reconcile(dir, map[string]string{"standard": path}); err == nil {
		t.Fatal("different built runtime accepted")
	}
	proof["runtimeManifestSha256"] = manifests["standard"]
	put()
	if err := os.WriteFile(filepath.Join(dir, "chrootctl-standard-arm64.zip"), []byte("tampered"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := reconcile(dir, nil); err == nil {
		t.Fatal("tampered hosted archive accepted")
	}
}
