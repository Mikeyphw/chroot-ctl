package cli

import (
	"strings"
	"testing"

	"chrootctl/internal/clipboard"
)

func TestCHR14ClipboardSetExplicitEmptyDoesNotReadStdin(t *testing.T) {
	inv, err := Parse([]string{"clipboard", "set", ""})
	if err != nil {
		t.Fatal(err)
	}
	text, err := clipboardSetText(inv, strings.NewReader("stdin should not be read"))
	if err != nil {
		t.Fatal(err)
	}
	if text != "" {
		t.Fatalf("explicit empty text became %q", text)
	}
}

func TestCHR14ClipboardSetStdinPreservesTrailingNewlinesAndCapsInput(t *testing.T) {
	inv, err := Parse([]string{"clipboard", "set"})
	if err != nil {
		t.Fatal(err)
	}
	text, err := clipboardSetText(inv, strings.NewReader("a\n\n"))
	if err != nil {
		t.Fatal(err)
	}
	if text != "a\n\n" {
		t.Fatalf("stdin text mismatch: %q", text)
	}
	tooLarge := strings.NewReader(strings.Repeat("x", clipboard.MaxClipboardTextBytes+1))
	if _, err = clipboardSetText(inv, tooLarge); err == nil || !strings.Contains(err.Error(), "exceeds 1 MiB") {
		t.Fatalf("expected size rejection, got %v", err)
	}
}
