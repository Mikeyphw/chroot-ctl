package repoctl

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

var forbiddenLegacyPaths = []string{"src", "tests", "pyproject.toml", "manage_source.py"}
var buildValidationFiles = []string{"build.sh", ".devtool.toml", ".github/workflows/ci.yml", "scripts/repoctl", "scripts/release", "scripts/final-seal"}
var forbiddenBuildTokens = []string{"python3", "setup-python", "pytest", "mypy", "nuitka"}
var transientCacheDirs = map[string]bool{"__pycache__": true, ".pytest_cache": true, ".mypy_cache": true, ".ruff_cache": true}

func pythonPackagingResidueDir(name string) bool {
	lower := strings.ToLower(name)
	return strings.HasSuffix(lower, ".egg-info") || strings.HasSuffix(lower, ".dist-info")
}

func pythonBytecode(name string) bool {
	lower := strings.ToLower(name)
	return strings.HasSuffix(lower, ".pyc") || strings.HasSuffix(lower, ".pyo")
}

// PurgeLegacyPythonResidue removes only generated Python residue which can be
// created by GO16 validation/package installation: bytecode/cache directories
// and Python packaging metadata (*.egg-info/*.dist-info). It deliberately
// refuses to remove real files from the legacy src/tests trees so the final
// purge remains fail-closed if Devtool did not delete a tracked migration file.
func PurgeLegacyPythonResidue(root string) error {
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if path == root {
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		slash := filepath.ToSlash(rel)
		parts := strings.Split(slash, "/")
		if d.IsDir() && (parts[0] == ".git" || parts[0] == ".devtool" || parts[0] == "out" || parts[0] == "dist" || parts[0] == "build") {
			return filepath.SkipDir
		}
		if d.IsDir() && (transientCacheDirs[d.Name()] || pythonPackagingResidueDir(d.Name())) {
			if err := os.RemoveAll(path); err != nil {
				return err
			}
			return filepath.SkipDir
		}
		if !d.IsDir() && pythonBytecode(d.Name()) {
			return os.Remove(path)
		}
		return nil
	})
	if err != nil {
		return err
	}
	for _, rel := range []string{"src", "tests"} {
		if err := pruneLegacyTree(filepath.Join(root, rel), root); err != nil {
			return err
		}
	}
	return nil
}

func pruneLegacyTree(path, root string) error {
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
			if err := pruneLegacyTree(child, root); err != nil {
				return err
			}
			continue
		}
		rel, _ := filepath.Rel(root, child)
		return fmt.Errorf("GO17 unexpected legacy file remains: %s", filepath.ToSlash(rel))
	}
	entries, err = os.ReadDir(path)
	if err != nil {
		return err
	}
	if len(entries) == 0 {
		return os.Remove(path)
	}
	return nil
}

func validateGeneratedLegacyResidue(path, root string) error {
	return filepath.WalkDir(path, func(child string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if child == path {
			return nil
		}
		if d.IsDir() && (transientCacheDirs[d.Name()] || pythonPackagingResidueDir(d.Name())) {
			return filepath.SkipDir
		}
		if d.IsDir() {
			return nil
		}
		if pythonBytecode(d.Name()) {
			return nil
		}
		rel, _ := filepath.Rel(root, child)
		return fmt.Errorf("GO17 unexpected legacy file remains: %s", filepath.ToSlash(rel))
	})
}

func ValidateRepositoryPurity(root string) error {
	// Normal `go test ./...` may run packages concurrently. Purity validation
	// therefore MUST NOT mutate the repository: doing so races source-archive
	// tests and other package processes. Generated GO16 residue is tolerated here
	// only when it is provably cache/package metadata. FinalSeal performs the
	// destructive safe-residue purge before requiring legacy paths to disappear.
	for _, rel := range forbiddenLegacyPaths {
		path := filepath.Join(root, filepath.FromSlash(rel))
		st, err := os.Lstat(path)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return err
		}
		if (rel == "src" || rel == "tests") && st.IsDir() {
			if err := validateGeneratedLegacyResidue(path, root); err != nil {
				return err
			}
			continue
		}
		return fmt.Errorf("GO17 legacy path remains: %s", rel)
	}
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if path == root {
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		slash := filepath.ToSlash(rel)
		parts := strings.Split(slash, "/")
		if d.IsDir() && (parts[0] == ".git" || parts[0] == ".devtool" || parts[0] == "out" || parts[0] == "dist" || parts[0] == "build") {
			return filepath.SkipDir
		}
		if d.IsDir() && (transientCacheDirs[d.Name()] || pythonPackagingResidueDir(d.Name())) {
			return filepath.SkipDir
		}
		if !d.IsDir() {
			lowerName := strings.ToLower(d.Name())
			if strings.HasSuffix(lowerName, ".py") || pythonBytecode(lowerName) {
				return fmt.Errorf("GO17 Python source/bytecode remains: %s", slash)
			}
		}
		return nil
	})
	if err != nil {
		return err
	}
	for _, rel := range buildValidationFiles {
		data, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
		if err != nil {
			return fmt.Errorf("read purity target %s: %w", rel, err)
		}
		lower := strings.ToLower(string(data))
		for _, token := range forbiddenBuildTokens {
			if strings.Contains(lower, token) {
				return fmt.Errorf("GO17 forbidden build/validation token %q remains in %s", token, rel)
			}
		}
	}
	devtool, err := os.ReadFile(filepath.Join(root, ".devtool.toml"))
	if err != nil {
		return err
	}
	if strings.Contains(strings.ToLower(string(devtool)), `type = "python"`) || strings.Contains(strings.ToLower(string(devtool)), "[python]") {
		return fmt.Errorf("GO17 Python Devtool target/config remains")
	}
	return nil
}
