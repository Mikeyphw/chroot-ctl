package factory

import (
	"testing"

	"chrootctl/internal/install"
)

func TestBuild(t *testing.T) {
	base := &install.Base{}
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
