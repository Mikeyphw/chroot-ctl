package contractgen

import (
	"path/filepath"
	"testing"
)

func TestGeneratedCLIArtifactsAreCurrent(t *testing.T) {
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	if err := Check(root); err != nil {
		t.Fatal(err)
	}
}
