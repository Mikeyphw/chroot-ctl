package repoctl

import (
	"os"
	"strings"
	"testing"
)

func TestCUX03CapabilityTruthAndVisibleBugRemediation(t *testing.T) {
	bridge, err := os.ReadFile("../module/webroot/chrootctl.js")
	if err != nil {
		t.Fatal(err)
	}
	ui, err := os.ReadFile("../module/webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	html, err := os.ReadFile("../module/webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	b, j, h := string(bridge), string(ui), string(html)
	for _, op := range []string{"debug.probes", "debug.timeline", "release.readiness", "smoke.last_result"} {
		if !strings.Contains(b, "'"+op+"'") {
			t.Fatalf("CUX03 query allow-list missing %q", op)
		}
	}
	if strings.Contains(h, `data-route="readiness"`) {
		t.Fatal("legacy Debug & readiness remains a separate global route")
	}
	for _, want := range []string{"if(name==='readiness')name='diagnostics'", "function readinessReason", "Rclone is unavailable", "System → Diagnostics"} {
		if !strings.Contains(j, want) {
			t.Fatalf("CUX03 UI invariant missing %q", want)
		}
	}
	if !strings.Contains(j, "el.disabled=!available") {
		t.Fatal("rclone unavailable state does not gate configuration controls")
	}
}
