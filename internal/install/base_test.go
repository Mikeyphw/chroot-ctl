package install

import (
	"chrootctl/internal/config"
	"context"
	"testing"
)

func TestPhaseAndDesktopSelection(t *testing.T) {
	if i := PhaseIndex(Bootstrap); i != 1 {
		t.Fatal(i)
	}
	if n, ok := NextPhase(Bootstrap); !ok || n != Desktop {
		t.Fatalf("%v %v", n, ok)
	}
	b := Base{Config: config.Default(config.RuntimeContext{Home: t.TempDir()})}
	d, e := b.SelectedDesktop("auto", "xfce4")
	if e != nil || d != "xfce4" {
		t.Fatalf("%s %v", d, e)
	}
	if _, e = b.SelectedDesktop("plasma", "minimal"); e == nil {
		t.Fatal("expected minimal error")
	}
}
func TestContextResumeMismatchFailsClosed(t *testing.T) {
	_ = context.Background()
	b := Base{}
	b.ContextKey = "new"
	if b.SelectedProfile("") != "minimal" {
		t.Fatal()
	}
}
func TestMirrorPlanNormalizes(t *testing.T) {
	b := Base{}
	b.ConfigureMirrorPlan("", "https://example/a/", []MirrorCandidate{{ID: " one ", URL: "https://m/"}, {}})
	if b.MirrorSelection != "auto" || b.MirrorBaseURL != "https://example/a" || len(b.MirrorCandidates) != 1 {
		t.Fatalf("%+v", b)
	}
}
