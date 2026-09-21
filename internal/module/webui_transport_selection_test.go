package module

import (
	"os"
	"strings"
	"testing"
)

func TestWebUITransportSelectionDoesNotMistakeKSUHostForStandalone(t *testing.T) {
	b, err := os.ReadFile("webroot/chrootctl.js")
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	required := []string{
		"const standaloneHTTP = loopbackHTTP && !isKernelSUAvailable();",
		"new URL(path,window.location.origin).href",
		"credentials:'same-origin'",
		"export function transportKind()",
	}
	for _, want := range required {
		if !strings.Contains(s, want) {
			t.Fatalf("transport selection missing %q", want)
		}
	}
	if strings.Contains(s, "const standaloneHTTP = typeof window") {
		t.Fatal("loopback hostname alone must not select standalone HTTP")
	}
}
