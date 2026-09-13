package cli

import (
	"bytes"
	"strings"
	"testing"
)

func TestCHR12ReadPasswordRequiresExactConfirmationAndPreservesSpaces(t *testing.T) {
	app := &App{Stdin: strings.NewReader("  secret  \n  secret  \n"), Stderr: &bytes.Buffer{}}
	got, err := app.readPassword()
	if err != nil {
		t.Fatal(err)
	}
	if got != "  secret  " {
		t.Fatalf("password was not preserved exactly: %q", got)
	}
}

func TestCHR12ReadPasswordRejectsConfirmationMismatch(t *testing.T) {
	app := &App{Stdin: strings.NewReader("secret\nother\n"), Stderr: &bytes.Buffer{}}
	if _, err := app.readPassword(); err == nil {
		t.Fatal("expected confirmation mismatch")
	}
}
