package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSWUI03StandaloneBrowserTransportAndAction(t *testing.T) {
	root := filepath.Join("..", "..")
	read := func(rel string) string {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	js := read("internal/module/webroot/chrootctl.js")
	for _, want := range []string{"standaloneHTTP", "/api/v1/health", "/api/v1/capabilities", "X-CSRF-Token", "credentials:'same-origin'", "transportAvailable"} {
		if !strings.Contains(js, want) {
			t.Fatalf("standalone frontend missing %q", want)
		}
	}
	if strings.Contains(js, "fetch('/shell") || strings.Contains(js, "fetch('/exec") {
		t.Fatal("standalone frontend exposes raw command route")
	}
	mod := read("internal/module/module.go")
	for _, want := range []string{"action.sh", "webui serve --open", "standalone-webui.log"} {
		if !strings.Contains(mod, want) {
			t.Fatalf("module launcher missing %q", want)
		}
	}
	main := read("cmd/chrootctl/main.go")
	for _, want := range []string{"StaticDir", "android.intent.action.VIEW", `args[1] == "start"`} {
		if !strings.Contains(main, want) {
			t.Fatalf("browser launcher missing %q", want)
		}
	}
}
