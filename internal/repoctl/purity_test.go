package repoctl

import (
	"os"
	"path/filepath"
	"testing"
)

func TestGO17RepositoryPurity(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err = ValidateRepositoryPurity(root); err != nil {
		t.Fatal(err)
	}
}

func TestPurgeLegacyPythonResidueIsCacheOnly(t *testing.T) {
	root := t.TempDir()
	for _, rel := range []string{
		"src/chrootctl/__pycache__/config.cpython-314.pyc",
		"src/chrootctl.egg-info/PKG-INFO",
		"src/chrootctl.egg-info/SOURCES.txt",
		"tests/__pycache__/test_cli.cpython-314.pyc",
		"scripts/__pycache__/helper.cpython-314.pyc",
	} {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte("cache"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	if err := PurgeLegacyPythonResidue(root); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, "src")); !os.IsNotExist(err) {
		t.Fatalf("src residue remains: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "tests")); !os.IsNotExist(err) {
		t.Fatalf("tests residue remains: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "scripts", "__pycache__")); !os.IsNotExist(err) {
		t.Fatalf("scripts cache remains: %v", err)
	}

	unexpected := filepath.Join(root, "src", "chrootctl", "unexpected.txt")
	if err := os.MkdirAll(filepath.Dir(unexpected), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(unexpected, []byte("must not be deleted"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := PurgeLegacyPythonResidue(root); err == nil {
		t.Fatal("expected unexpected legacy file to fail closed")
	}
	if _, err := os.Stat(unexpected); err != nil {
		t.Fatalf("unexpected file was deleted: %v", err)
	}
}

func TestValidateRepositoryPurityToleratesGeneratedResidueWithoutDeletingIt(t *testing.T) {
	root := t.TempDir()
	for _, rel := range []string{
		"src/chrootctl.egg-info/PKG-INFO",
		"tests/__pycache__/test_cli.cpython-314.pyc",
	} {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte("generated"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	// Supply the non-legacy purity targets expected by ValidateRepositoryPurity.
	for _, rel := range buildValidationFiles {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte("go-native\n"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	if err := ValidateRepositoryPurity(root); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, "src", "chrootctl.egg-info", "PKG-INFO")); err != nil {
		t.Fatalf("validation mutated generated residue: %v", err)
	}
}
