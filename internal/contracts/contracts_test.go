package contracts

import (
	"path/filepath"
	"runtime"
	"testing"
)

func contractDir(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "migration", "contracts", "v1"))
}

func TestFrozenMigrationContractsValidate(t *testing.T) {
	bundle, err := LoadDir(contractDir(t))
	if err != nil {
		t.Fatalf("LoadDir: %v", err)
	}
	if err := bundle.Validate(); err != nil {
		t.Fatalf("Validate: %v", err)
	}
}

func TestCriticalBridgeOperationsAreFrozen(t *testing.T) {
	bundle, err := LoadDir(contractDir(t))
	if err != nil {
		t.Fatalf("LoadDir: %v", err)
	}
	operations := make(map[string]BridgeOperation, len(bundle.Bridge.Operations))
	for _, operation := range bundle.Bridge.Operations {
		operations[operation.Name] = operation
	}
	for _, name := range []string{
		"system.dashboard",
		"install.run",
		"operations.retry",
		"smoke.run",
		"final.release_seal",
	} {
		if _, ok := operations[name]; !ok {
			t.Errorf("critical bridge operation missing from baseline: %s", name)
		}
	}
}

func TestGO13RuntimeContractIsGoNative(t *testing.T) {
	bundle, err := LoadDir(contractDir(t))
	if err != nil {
		t.Fatalf("LoadDir: %v", err)
	}
	if bundle.Release.CompatibilitySchemaVersion != 3 {
		t.Fatalf("compatibility schema = %d, want 3", bundle.Release.CompatibilitySchemaVersion)
	}
	if bundle.Release.Backend.Implementation != "go" {
		t.Fatalf("backend implementation = %q, want go", bundle.Release.Backend.Implementation)
	}
	if bundle.Release.Backend.Version == "" {
		t.Fatal("backend version is empty")
	}
	if bundle.Release.NativeRuntime.SchemaVersion != 2 {
		t.Fatalf("native runtime schema = %d, want 2", bundle.Release.NativeRuntime.SchemaVersion)
	}
	if bundle.Release.NativeRuntime.Kind != "go-native" {
		t.Fatalf("native runtime kind = %q, want go-native", bundle.Release.NativeRuntime.Kind)
	}
}
