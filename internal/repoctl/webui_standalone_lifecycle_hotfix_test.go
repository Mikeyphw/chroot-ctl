package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestStandaloneWebUILifecycleHotfix(t *testing.T) {
	root := filepath.Join("..", "..")
	read := func(rel string) string {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	module := read("internal/module/module.go")
	for _, want := range []string{"command -v setsid", "busybox --list", "standalone-webui.pid", "kill -0", "/proc/$OLD_PID/cmdline", "standalone-webui.log"} {
		if !strings.Contains(module, want) {
			t.Fatalf("standalone Action lifecycle missing %q", want)
		}
	}
	server := read("internal/standalonewebui/server.go")
	for _, want := range []string{"request begin method=%s path=%s", "serve stopped unexpectedly", "request panic", "idle timeout reached"} {
		if !strings.Contains(server, want) {
			t.Fatalf("standalone server diagnostics missing %q", want)
		}
	}
	frontend := read("internal/module/webroot/chrootctl.js")
	for _, want := range []string{"cache:'no-store'", "Standalone backend listener is unreachable", "standalone-webui.log", "setTimeout(resolve,250)"} {
		if !strings.Contains(frontend, want) {
			t.Fatalf("standalone frontend lifecycle diagnostic missing %q", want)
		}
	}
}
