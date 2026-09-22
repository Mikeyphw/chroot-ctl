package cli

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRootHelpListsRealCommandsAndWrapper(t *testing.T) {
	help := RootHelp()
	for _, want := range []string{"usage: chrootctl [global options] COMMAND [arguments]", "commands:", "status", "chroots", "wrapper", "Examples:"} {
		if !strings.Contains(help, want) {
			t.Fatalf("RootHelp missing %q:\n%s", want, help)
		}
	}
	if strings.Contains(help, "unknown command: COMMAND") {
		t.Fatalf("RootHelp should describe COMMAND as a placeholder, not a literal command: %s", help)
	}
}

func TestWrongCommandArgumentsPrintCommandUsage(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := Run(context.Background(), []string{"status", "--bad"}, nil, &stdout, &stderr)
	if code != 2 {
		t.Fatalf("code=%d stderr=%s", code, stderr.String())
	}
	text := stderr.String()
	if !strings.Contains(text, "unrecognized argument: --bad") || !strings.Contains(text, "usage: chrootctl status") || !strings.Contains(text, "--details") {
		t.Fatalf("stderr did not include status usage:\n%s", text)
	}
}

func TestMissingRequiredArgumentPrintsSpecificUsage(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := Run(context.Background(), []string{"magisk", "render"}, nil, &stdout, &stderr)
	if code != 2 {
		t.Fatalf("code=%d stderr=%s", code, stderr.String())
	}
	text := stderr.String()
	if !strings.Contains(text, "output is required") || !strings.Contains(text, "usage: chrootctl magisk render") || !strings.Contains(text, "--output") {
		t.Fatalf("stderr did not include magisk render usage:\n%s", text)
	}
}

func TestWrapperInstallWritesExecutableAndCompletion(t *testing.T) {
	dir := t.TempDir()
	completionDir := t.TempDir()
	var stdout, stderr bytes.Buffer
	code := Run(context.Background(), []string{"wrapper", "install", "--dir", dir, "--name", "chc", "--completion-dir", completionDir}, nil, &stdout, &stderr)
	if code != 0 {
		t.Fatalf("code=%d stdout=%s stderr=%s", code, stdout.String(), stderr.String())
	}
	wrapperPath := filepath.Join(dir, "chc")
	info, err := os.Stat(wrapperPath)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o755 {
		t.Fatalf("wrapper mode=%o", info.Mode().Perm())
	}
	wrapper, err := os.ReadFile(wrapperPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(wrapper), wrapperMarker) || !strings.Contains(string(wrapper), "chrootctl") || strings.Contains(string(wrapper), "exec su -c") {
		t.Fatalf("unexpected wrapper content:\n%s", wrapper)
	}
	completionPath := filepath.Join(completionDir, "_chrootctl")
	completion, err := os.ReadFile(completionPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(completion), "#compdef chrootctl chc") || !strings.Contains(string(completion), "compdef _chrootctl chrootctl chc") {
		t.Fatalf("completion does not include wrapper compdef:\n%s", completion)
	}
}
