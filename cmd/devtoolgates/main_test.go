package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestNativeSourceGates(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	for _, gate := range []struct {
		name string
		run  func(string) ([]check, error)
	}{{"actions", actionsChecks}, {"r1", r1Checks}} {
		checks, err := gate.run(root)
		if err != nil {
			t.Fatalf("%s source: %v", gate.name, err)
		}
		if err := allChecks(checks); err != nil {
			t.Fatalf("%s: %v", gate.name, err)
		}
	}
}

func TestNativeSourceGatesRejectTampering(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	for _, p := range testInputPaths() {
		data, err := os.ReadFile(filepath.Join(root, p))
		if err != nil {
			t.Fatal(err)
		}
		path := filepath.Join(dir, p)
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	ci := filepath.Join(dir, ".github/workflows/ci.yml")
	original, err := os.ReadFile(ci)
	if err != nil {
		t.Fatal(err)
	}
	tampered := strings.Replace(string(original), "setup-android@v4", "setup-android@v3", 1)
	if tampered == string(original) {
		t.Fatal("fixture missing current v4 binding")
	}
	if err := os.WriteFile(ci, []byte(tampered), 0600); err != nil {
		t.Fatal(err)
	}
	checks, err := actionsChecks(dir)
	if err == nil && allChecks(checks) == nil {
		t.Fatal("v3 regression accepted")
	}
	if err := os.WriteFile(ci, original, 0600); err != nil {
		t.Fatal(err)
	}
	gateFile := filepath.Join(dir, testR1File())
	contents, err := os.ReadFile(gateFile)
	if err != nil {
		t.Fatal(err)
	}
	erased := strings.Replace(string(contents), testR1Token(), "REMOVED_CONTRACT", 1)
	if erased == string(contents) {
		t.Fatal("fixture missing R1 contract")
	}
	if err := os.WriteFile(gateFile, []byte(erased), 0600); err != nil {
		t.Fatal(err)
	}
	checks, err = r1Checks(dir)
	if err == nil && allChecks(checks) == nil {
		t.Fatal("removed R1 marker accepted")
	}
	if err := os.Remove(gateFile); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(root, testR1File()), gateFile); err != nil {
		t.Fatal(err)
	}
	if _, err := r1Checks(dir); err == nil {
		t.Fatal("symlinked source accepted")
	}
}

func testInputPaths() []string {
	return []string{".github/workflows/ci.yml", ".github/workflows/devtool-chrootctl-build.yml", chMain, chClient}
}
func testR1File() string  { return chClient }
func testR1Token() string { return "skybind-r1-grant-handoff-v1" }
