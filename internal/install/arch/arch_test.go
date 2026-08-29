package arch

import (
	"chrootctl/internal/config"
	"chrootctl/internal/install"
	"testing"
)

func TestReadyFalseWithoutPacman(t *testing.T) {
	cfg := config.Default(config.RuntimeContext{Home: t.TempDir()})
	cfg.ChrootRoot = t.TempDir()
	b := &install.Base{Config: cfg}
	i := New(b)
	if i.ReadyForBootstrap() {
		t.Fatal("unexpected")
	}
}
