package completion

import (
	"chrootctl/internal/registry"
	"strings"
	"testing"
)

func TestCommandCountAndNames(t *testing.T) {
	if len(CommandNodes) != 68 {
		t.Fatalf("nodes=%d", len(CommandNodes))
	}
	z := GenerateZsh()
	if !strings.Contains(z, "#compdef chrootctl chc") || !strings.Contains(z, "compdef _chrootctl chrootctl chc") || !strings.Contains(z, "1:distro:(ubuntu arch)") {
		t.Fatal(z)
	}
	s := ChrootNames([]registry.Chroot{{Name: "b", Installed: false}, {Name: "a", Installed: true}}, true)
	if s != "a" {
		t.Fatal(s)
	}
}
