package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func mustParseWrapper(t *testing.T, args ...string) Invocation {
	t.Helper()
	inv, err := Parse(args)
	if err != nil {
		t.Fatal(err)
	}
	return inv
}

func TestCHR04WrapperIsThinTrustedLauncher(t *testing.T) {
	script := wrapperScript()
	for _, forbidden := range []string{"sed ", "command -v", "su -c", "modules_update", "${PATH", "termux"} {
		if strings.Contains(script, forbidden) {
			t.Fatalf("wrapper contains forbidden trust-boundary token %q", forbidden)
		}
	}
	for _, required := range []string{"/system/bin/chrootctl", "/data/adb/modules/chrootctl-magisk/system/bin/chrootctl", wrapperMarker} {
		if !strings.Contains(script, required) {
			t.Fatalf("wrapper missing %q", required)
		}
	}
}

func TestCHR04WrapperDryRunDoesNotWrite(t *testing.T) {
	root := t.TempDir()
	binDir := filepath.Join(root, "bin")
	completionDir := filepath.Join(root, "zsh")
	inv := mustParseWrapper(t, "--dry-run", "wrapper", "install", "--dir", binDir, "--completion-dir", completionDir, "--name", "safe")
	var stdout, stderr bytes.Buffer
	if code := InstallWrapper(inv, &stdout, &stderr); code != 0 {
		t.Fatalf("code=%d stderr=%s", code, stderr.String())
	}
	if _, err := os.Stat(binDir); !os.IsNotExist(err) {
		t.Fatalf("dry-run created wrapper dir: %v", err)
	}
	if _, err := os.Stat(completionDir); !os.IsNotExist(err) {
		t.Fatalf("dry-run created completion dir: %v", err)
	}
	if !strings.Contains(stdout.String(), "Would install wrapper") {
		t.Fatalf("missing plan: %s", stdout.String())
	}
}

func TestCHR04WrapperRefusesForeignCollisionWithoutForce(t *testing.T) {
	root := t.TempDir()
	binDir := filepath.Join(root, "bin")
	if err := os.MkdirAll(binDir, 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(binDir, "chc")
	if err := os.WriteFile(path, []byte("#!/bin/sh\necho foreign\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	inv := mustParseWrapper(t, "wrapper", "install", "--dir", binDir, "--no-completion")
	var stdout, stderr bytes.Buffer
	if code := InstallWrapper(inv, &stdout, &stderr); code == 0 {
		t.Fatal("foreign collision unexpectedly replaced")
	}
	got, _ := os.ReadFile(path)
	if !strings.Contains(string(got), "foreign") {
		t.Fatalf("foreign file changed: %s", got)
	}
}

func TestCHR04WrapperForceAndCustomCompletionAlias(t *testing.T) {
	root := t.TempDir()
	binDir := filepath.Join(root, "bin")
	zshDir := filepath.Join(root, "zsh")
	if err := os.MkdirAll(binDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(binDir, "foo"), []byte("foreign"), 0o755); err != nil {
		t.Fatal(err)
	}
	inv := mustParseWrapper(t, "wrapper", "install", "--dir", binDir, "--completion-dir", zshDir, "--name", "foo", "--force")
	var stdout, stderr bytes.Buffer
	if code := InstallWrapper(inv, &stdout, &stderr); code != 0 {
		t.Fatalf("code=%d stderr=%s", code, stderr.String())
	}
	wrapper, err := os.ReadFile(filepath.Join(binDir, "foo"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(wrapper, []byte(wrapperMarker)) {
		t.Fatal("missing wrapper provenance")
	}
	completionText, err := os.ReadFile(filepath.Join(zshDir, "_chrootctl"))
	if err != nil {
		t.Fatal(err)
	}
	text := string(completionText)
	if !strings.HasPrefix(text, completionMarker+"\n") || !strings.Contains(text, "#compdef chrootctl foo") || !strings.Contains(text, "compdef _chrootctl chrootctl foo") {
		t.Fatalf("custom completion registration missing:\n%s", text[:min(len(text), 300)])
	}
}

func TestCHR04WrapperNameValidation(t *testing.T) {
	for _, name := range []string{"../bad", "bad name", "a;id", strings.Repeat("a", 65)} {
		inv := mustParseWrapper(t, "wrapper", "install", "--name", name, "--no-completion", "--dir", t.TempDir())
		var stdout, stderr bytes.Buffer
		if code := InstallWrapper(inv, &stdout, &stderr); code != 2 {
			t.Fatalf("name %q code=%d", name, code)
		}
	}
}
