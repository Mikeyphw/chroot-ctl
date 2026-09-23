package module

import (
	"os"
	"strings"
	"testing"
)

func TestWebUIKSUTransportMatchesProvenHostABI(t *testing.T) {
	k, err := os.ReadFile("webroot/kernelsu.js")
	if err != nil {
		t.Fatal(err)
	}
	s := string(k)
	if !strings.Contains(s, "native.spawn(shellCommand(command, args), JSON.stringify([]), JSON.stringify(options), name)") {
		t.Fatal("spawn must cross the KSU root-shell boundary as one quoted command with empty native argv")
	}
	if strings.Contains(s, "native.spawn(command, JSON.stringify(args), JSON.stringify(options), name)") {
		t.Fatal("raw argv must not be handed to the KSU host because the Android bridge concatenates it without shell escaping")
	}
	for _, want := range []string{"pendingExitCode", "child.bridgeError", "setTimeout(() => finishExit(code), 500)"} {
		if !strings.Contains(s, want) {
			t.Fatalf("missing non-zero KSU diagnostic retention contract %q", want)
		}
	}
	i, err := os.ReadFile("webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	ui := string(i)
	for _, want := range []string{"Checking backend", "Checking backend transport", "Checking backend capabilities", "WebUI startup error", "unhandledrejection"} {
		if !strings.Contains(ui, want) {
			t.Fatalf("missing startup diagnostic %q", want)
		}
	}
}
