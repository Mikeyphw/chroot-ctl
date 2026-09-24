package completion

import (
	"chrootctl/internal/clicontract"
	"chrootctl/internal/registry"
	"strings"
	"testing"
)

func TestCommandCountAndNames(t *testing.T) {
	if len(CommandNodes) != 92 {
		t.Fatalf("nodes=%d", len(CommandNodes))
	}
	z, err := GenerateZsh()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(z, "#compdef chrootctl chc") || !strings.Contains(z, "compdef _chrootctl chrootctl chc") || !strings.Contains(z, "1:distro:(ubuntu arch)") {
		t.Fatal(z)
	}
	s := ChrootNames([]registry.Chroot{{Name: "b", Installed: false}, {Name: "a", Installed: true}}, true)
	if s != "a" {
		t.Fatal(s)
	}
}

func TestGeneratedCompletionCoversEveryExposedContractNodeAndOption(t *testing.T) {
	z, err := GenerateZsh()
	if err != nil {
		t.Fatal(err)
	}
	for _, spec := range clicontract.CommandSpecs {
		if spec.Hidden || !spec.CompletionExposed || spec.Command == "app" || spec.Command == "__complete" {
			continue
		}
		if !strings.Contains(z, spec.Path[0]) {
			t.Fatalf("completion missing command root %q", spec.Path[0])
		}
		if len(spec.Path) > 1 && !strings.Contains(z, spec.Command+"*") {
			t.Fatalf("completion missing command path %q", spec.Command)
		}
		for _, arg := range spec.Arguments {
			for _, option := range arg.Options {
				if !strings.Contains(z, option+"[") {
					t.Fatalf("completion missing %s option %s", spec.Command, option)
				}
			}
		}
	}
}
