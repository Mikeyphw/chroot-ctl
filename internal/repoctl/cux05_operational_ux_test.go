package repoctl

import (
	"os"
	"strings"
	"testing"
)

func TestCUX05OperationalUX(t *testing.T) {
	hb, err := os.ReadFile("../module/webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	jb, err := os.ReadFile("../module/webroot/index.js")
	if err != nil {
		t.Fatal(err)
	}
	h, j := string(hb), string(jb)
	for _, want := range []string{`data-section="sessions"`, `data-section="operations"`, `data-section="activity"`, `id="jobs-list"`, `id="activity-list"`, `data-activity-filter="failed"`} {
		if !strings.Contains(h, want) {
			t.Fatalf("CUX05 surface missing %q", want)
		}
	}
	for _, want := range []string{"function operationCard", "function activeJob", "operationsState.activityFilter", "openOperation(b.dataset.operationId)", "currentSection==='operations'||currentSection==='activity'"} {
		if !strings.Contains(j, want) {
			t.Fatalf("CUX05 behavior missing %q", want)
		}
	}
	for _, want := range []string{"createSession(", "captureSession(", "inputSession(", "detachSession(", "killSession(", "cancelOperation(", "retryOperation("} {
		if !strings.Contains(j, want) {
			t.Fatalf("CUX05 operational capability missing %q", want)
		}
	}
	if strings.Contains(h, `data-section="logs"><span class="nav-glyph" aria-hidden="true">≡</span><span>Activity</span>`) {
		t.Fatal("Activity still aliases the Logs workspace")
	}
}
