package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTmux06WebUISessionBoundary(t *testing.T) {
	root := filepath.Join("..", "..")
	read := func(n string) string {
		b, e := os.ReadFile(filepath.Join(root, n))
		if e != nil {
			t.Fatal(e)
		}
		return string(b)
	}
	js := read("internal/module/webroot/chrootctl.js")
	ui := read("internal/module/webroot/index.js")
	html := read("internal/module/webroot/index.html")
	backend := read("internal/bridge/backend.go")
	for _, w := range []string{"sessions.list", "sessions.capture", "sessions.create", "sessions.detach", "sessions.kill"} {
		if !strings.Contains(js, w) {
			t.Fatalf("missing %s", w)
		}
	}
	for _, w := range []string{"sessions-panel", "terminal-output", "Create / reconnect"} {
		if !strings.Contains(html, w) {
			t.Fatalf("missing UI %s", w)
		}
	}
	for _, w := range []string{"captureSession", "attachSession", "refreshTerminal", "Recovery needed"} {
		if !strings.Contains(ui, w) {
			t.Fatalf("missing client %s", w)
		}
	}
	for _, forbidden := range []string{
		`exec("tmux`, `exec('tmux`, `spawn("tmux`, `spawn('tmux`,
		`ksu.exec(`, `ksu.spawn(`,
	} {
		if strings.Contains(ui, forbidden) {
			t.Fatalf("WebUI must not execute tmux/raw KernelSU commands: found %q", forbidden)
		}
	}
	// chrootctl.js is the established allow-listed KernelSU transport. Session
	// operations must go through the structured app protocol, never a tmux argv.
	for _, forbidden := range []string{`["tmux"`, `['tmux'`, `,"tmux"`, `,'tmux'`} {
		if strings.Contains(js, forbidden) {
			t.Fatalf("session bridge must not construct a direct tmux argv: found %q", forbidden)
		}
	}
	if !strings.Contains(backend, "Sessions().Resize") {
		t.Fatal("capture transport must mediate PTY resize")
	}
}
