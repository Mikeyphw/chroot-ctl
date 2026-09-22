package repoctl

import (
	"os"
	"strings"
	"testing"
)

func TestCUX06TransferRcloneSystemUX(t *testing.T) {
	html, err := os.ReadFile("../module/webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	js, err := os.ReadFile("../module/webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	css, err := os.ReadFile("../module/webroot/index.css")
	if err != nil {
		t.Fatal(err)
	}
	hs, jsn, cs := string(html), string(js), string(css)
	for _, want := range []string{"Skip to main content", "Move chroots without guessing", "Browse first, transfer second", "Configuration, runtime and diagnostics", `data-route="diagnostics"`} {
		if !strings.Contains(hs, want) {
			t.Fatalf("CUX06 HTML missing %q", want)
		}
	}
	for _, want := range []string{"sectionOwnsRefresh", "Rclone status could not be loaded.", "Technical code:"} {
		if !strings.Contains(jsn, want) {
			t.Fatalf("CUX06 JS missing %q", want)
		}
	}
	for _, want := range []string{".skip-link", "min-height:44px", ":focus-visible", "#transfer-panel,#rclone-panel,#settings-panel"} {
		if !strings.Contains(cs, want) {
			t.Fatalf("CUX06 CSS missing %q", want)
		}
	}
	if strings.Contains(hs, "KERNELSU WEBUI") {
		t.Fatal("transport branding leaked into product UI")
	}
}
