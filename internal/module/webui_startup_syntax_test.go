package module

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"testing"
)

func TestWebUIModulesParseAndHTMLIDsAreUnique(t *testing.T) {
	root := filepath.Join("webroot")
	for _, name := range []string{"index.js", "chrootctl.js", "kernelsu.js"} {
		body, err := os.ReadFile(filepath.Join(root, name))
		if err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command("node", "--input-type=module", "--check")
		cmd.Stdin = bytes.NewReader(body)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("%s is not a valid ES module: %v\n%s", name, err, out)
		}
	}

	html, err := os.ReadFile(filepath.Join(root, "index.html"))
	if err != nil {
		t.Fatal(err)
	}
	re := regexp.MustCompile(`\bid=["']([^"']+)["']`)
	seen := map[string]bool{}
	for _, match := range re.FindAllSubmatch(html, -1) {
		id := string(match[1])
		if seen[id] {
			t.Fatalf("duplicate WebUI id %q can bind controls to the wrong section", id)
		}
		seen[id] = true
	}
}
