package testseal

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const SchemaVersion = 1

type Entry struct {
	Source      string   `json:"source"`
	Disposition string   `json:"disposition"`
	Targets     []string `json:"targets"`
	Rationale   string   `json:"rationale"`
}
type Map struct {
	SchemaVersion int     `json:"schemaVersion"`
	SourceSuite   string  `json:"sourceSuite"`
	SourceCount   int     `json:"sourceCount"`
	Entries       []Entry `json:"entries"`
}

func safeRel(v string) bool {
	if strings.TrimSpace(v) == "" || filepath.IsAbs(v) {
		return false
	}
	c := filepath.Clean(v)
	return c != "." && c != ".." && !strings.HasPrefix(c, ".."+string(filepath.Separator))
}
func Load(path string) (Map, error) {
	var m Map
	b, err := os.ReadFile(path)
	if err != nil {
		return m, err
	}
	if err = json.Unmarshal(b, &m); err != nil {
		return m, err
	}
	return m, nil
}
func Validate(root string, requireLegacySources bool) error {
	m, err := Load(filepath.Join(root, "migration", "go16-test-map.json"))
	if err != nil {
		return err
	}
	if m.SchemaVersion != SchemaVersion {
		return fmt.Errorf("GO16 test-map schema drift: expected %d got %d", SchemaVersion, m.SchemaVersion)
	}
	if m.SourceSuite != "legacy-python" {
		return fmt.Errorf("unexpected source suite %q", m.SourceSuite)
	}
	if m.SourceCount != len(m.Entries) || m.SourceCount != 82 {
		return fmt.Errorf("legacy test inventory drift: declared=%d decoded=%d expected=82", m.SourceCount, len(m.Entries))
	}
	seen := map[string]bool{}
	for _, e := range m.Entries {
		if !safeRel(e.Source) || !strings.HasPrefix(filepath.ToSlash(e.Source), "tests/test_") || !strings.HasSuffix(e.Source, ".py") {
			return fmt.Errorf("unsafe legacy test source %q", e.Source)
		}
		if seen[e.Source] {
			return fmt.Errorf("duplicate legacy test source %q", e.Source)
		}
		seen[e.Source] = true
		if e.Disposition != "go" && e.Disposition != "kotlin" && e.Disposition != "retired-contract" {
			return fmt.Errorf("invalid disposition %q for %s", e.Disposition, e.Source)
		}
		if strings.TrimSpace(e.Rationale) == "" {
			return fmt.Errorf("missing rationale for %s", e.Source)
		}
		if len(e.Targets) == 0 {
			return fmt.Errorf("missing target for %s", e.Source)
		}
		for _, target := range e.Targets {
			if !safeRel(target) {
				return fmt.Errorf("unsafe target %q for %s", target, e.Source)
			}
			st, err := os.Stat(filepath.Join(root, filepath.FromSlash(target)))
			if err != nil || !st.Mode().IsRegular() {
				return fmt.Errorf("mapped target missing for %s: %s", e.Source, target)
			}
			if e.Disposition == "go" && !strings.HasSuffix(target, "_test.go") {
				return fmt.Errorf("Go mapping must target _test.go: %s -> %s", e.Source, target)
			}
			if e.Disposition == "kotlin" && !strings.HasSuffix(target, "Test.kt") {
				return fmt.Errorf("Kotlin mapping must target Test.kt: %s -> %s", e.Source, target)
			}
		}
	}
	testsDir := filepath.Join(root, "tests")
	if requireLegacySources {
		rows, err := filepath.Glob(filepath.Join(testsDir, "test_*.py"))
		if err != nil {
			return err
		}
		got := make([]string, 0, len(rows))
		for _, p := range rows {
			rel, _ := filepath.Rel(root, p)
			got = append(got, filepath.ToSlash(rel))
		}
		sort.Strings(got)
		want := make([]string, 0, len(seen))
		for p := range seen {
			want = append(want, filepath.ToSlash(p))
		}
		sort.Strings(want)
		if len(got) != len(want) {
			return fmt.Errorf("unmapped legacy test inventory: filesystem=%d map=%d", len(got), len(want))
		}
		for i := range got {
			if got[i] != want[i] {
				return fmt.Errorf("legacy test map mismatch: filesystem=%q map=%q", got[i], want[i])
			}
		}
	} else {
		if err := validateFinalTestResidue(testsDir, root); err != nil {
			return err
		}
	}
	return nil
}

func validateFinalTestResidue(path, root string) error {
	entries, err := os.ReadDir(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	for _, entry := range entries {
		child := filepath.Join(path, entry.Name())
		if entry.IsDir() {
			if entry.Name() == "__pycache__" || strings.HasSuffix(strings.ToLower(entry.Name()), ".egg-info") || strings.HasSuffix(strings.ToLower(entry.Name()), ".dist-info") {
				continue
			}
			if err := validateFinalTestResidue(child, root); err != nil {
				return err
			}
			continue
		}
		lower := strings.ToLower(entry.Name())
		if strings.HasSuffix(lower, ".pyc") || strings.HasSuffix(lower, ".pyo") {
			continue
		}
		rel, _ := filepath.Rel(root, child)
		return fmt.Errorf("unexpected legacy test residue remains: %s", filepath.ToSlash(rel))
	}
	return nil
}
