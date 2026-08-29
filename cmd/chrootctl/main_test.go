package main

import "testing"

func TestVersionPath(t *testing.T) {
	if code := run([]string{"--version"}); code != 0 {
		t.Fatalf("run(--version)=%d, want 0", code)
	}
}
func TestHumanCLIStaticCompletionPath(t *testing.T) {
	if code := run([]string{"completion", "zsh"}); code != 0 {
		t.Fatalf("completion zsh=%d", code)
	}
}
func TestHumanCLIHelpPath(t *testing.T) {
	if code := run([]string{"status", "--help"}); code != 0 {
		t.Fatalf("status --help=%d", code)
	}
}
