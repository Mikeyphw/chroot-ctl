package repoctl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// S7 P04 remains a Go-native consumer: no tracked Python source may escape GO17.
func TestS7P04GoNativeConsumerContract(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateRepositoryPurity(root); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, "tests", "test_devtool_go_adoption.py")); !os.IsNotExist(err) {
		t.Fatalf("S7 P04 legacy Python test remains: %v", err)
	}
	data, err := os.ReadFile(filepath.Join(root, ".devtool.toml"))
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	for _, required := range []string{"[targets.chrootctl_go]", "[targets.chrootctl_root_module]"} {
		if !strings.Contains(text, required) {
			t.Fatalf("missing Devtool target %s", required)
		}
	}
	workflow, err := os.ReadFile(filepath.Join(root, ".github/workflows/devtool-s7-p04-go-consumer.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, required := range []string{
		"pull_request:", "workflow_dispatch:", "contents: read",
		"416d24140c7f7a4b9833d7cb19df50ca7e7363b8", "delivery adoption audit --json",
		"TestGO17RepositoryPurity", "go run ./cmd/devtoolgates actions",
	} {
		if !strings.Contains(string(workflow), required) {
			t.Fatalf("P04 hosted acceptance omitted %s", required)
		}
	}
}
