package ubuntu

import (
	"strings"
	"testing"
)

func TestParseReleaseAndTarball(t *testing.T) {
	html := `<a href="24.04/">24.04</a><a href="noble/">noble</a><a href="../">up</a>`
	r := ParseReleaseIndex(html)
	if len(r) != 2 {
		t.Fatalf("%+v", r)
	}
	name, url, e := ResolveTarball(`<a href="ubuntu-base-24.04-base-arm64.tar.gz">x</a>`, "arm64", "https://x/")
	if e != nil || !strings.Contains(name, "arm64") || url != "https://x/"+name {
		t.Fatalf("%s %s %v", name, url, e)
	}
}
func TestUnsupportedArch(t *testing.T) {
	if _, _, e := ResolveTarball("", "riscv64", "x"); e == nil {
		t.Fatal("expected")
	}
}
