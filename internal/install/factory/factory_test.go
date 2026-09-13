package factory

import (
	"testing"

	"chrootctl/internal/install"
	sys "chrootctl/internal/system"
)

func TestBuild(t *testing.T) {
	base := &install.Base{Runner: &sys.Runner{DryRun: true}}
	if _, err := Build("ubuntu", base); err != nil {
		t.Fatal(err)
	}
	if _, err := Build("arch", base); err != nil {
		t.Fatal(err)
	}
	if _, err := Build("void", base); err == nil {
		t.Fatal("expected unsupported distro")
	}
}
