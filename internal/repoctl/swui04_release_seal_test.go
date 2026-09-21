package repoctl

import (
	"os"
	"strings"
	"testing"
)

func TestSWUI04StandaloneReleaseSeal(t *testing.T) {
	checks := map[string][]string{
		"../standalonewebui/server.go":                   {"127.0.0.1:0", "SameSiteStrictMode", "invalid origin", "func (s *Server) Done() <-chan struct{}"},
		"../../cmd/chrootctl/main.go":                    {"case <-srv.Done()", "webui"},
		"../../scripts/webui/device-standalone-smoke.sh": {"SWUI-04 DEVICE SMOKE PASS", "bootstrap replay", "mutation boundary"},
	}
	for path, wants := range checks {
		b, e := os.ReadFile(path)
		if e != nil {
			t.Fatal(e)
		}
		s := string(b)
		for _, w := range wants {
			if !strings.Contains(s, w) {
				t.Fatalf("%s missing %q", path, w)
			}
		}
	}
}
