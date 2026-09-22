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
	if !strings.Contains(s, "native.spawn(command, JSON.stringify(args), JSON.stringify(options), name)") {
		t.Fatal("spawn must pass verbatim JSON argv to KSU host")
	}
	if strings.Contains(s, "JSON.stringify(args.map(shellQuote))") {
		t.Fatal("spawn must not pre-shell-quote argv")
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
