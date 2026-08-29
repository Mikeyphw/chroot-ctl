package catalog

import (
	"os"
	"path/filepath"
	"testing"
)

func TestBuiltinCatalogLoads(t *testing.T) {
	c := Catalog{Kind: "tool", ResourceRoot: "../../resources"}
	e, err := c.LoadAll()
	if err != nil {
		t.Fatal(err)
	}
	if len(e) < 10 {
		t.Fatalf("entries=%d", len(e))
	}
	cats, err := c.Categories("ubuntu")
	if err != nil || len(cats) == 0 {
		t.Fatalf("%v %v", cats, err)
	}
}
func TestExternalSafetyAndCategory(t *testing.T) {
	d := t.TempDir()
	p := filepath.Join(d, "x.yaml")
	_ = os.WriteFile(p, []byte("x"), 0o600)
	_ = os.Chmod(p, 0o666)
	if e := safeExternal(p, "manifest"); e == nil {
		t.Fatal("expected unsafe")
	}
	if c, e := normalizeCategory("Desktop Utility"); e != nil || c != "desktop-utility" {
		t.Fatalf("%s %v", c, e)
	}
}
