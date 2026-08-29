package clipboard

import (
	"chrootctl/internal/config"
	"testing"
)

func TestPathsTokenAndStatus(t *testing.T) {
	cfg := config.Default(config.RuntimeContext{Home: t.TempDir()})
	p := DefaultPaths(cfg)
	if p.PIDFile == "" || p.SocketPath == "" {
		t.Fatal(p)
	}
	a, _ := newToken()
	b, _ := newToken()
	if len(a) != 64 || a == b || !equal(a, a) || equal(a, b) {
		t.Fatal("token")
	}
	s := DaemonStatus(t.TempDir() + "/none")
	if s["running"].(bool) {
		t.Fatal(s)
	}
}
