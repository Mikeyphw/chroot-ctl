package validation

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"
)

type validationFixture struct {
	Validation struct {
		Cases []struct {
			Name      string `json:"name"`
			OK        bool   `json:"ok"`
			Value     any    `json:"value"`
			ErrorType string `json:"errorType"`
			Error     string `json:"error"`
		} `json:"cases"`
	} `json:"validation"`
}

func validationFixturePath(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "migration", "contracts", "v1", "foundations.json"))
}

func TestValidationParityFixture(t *testing.T) {
	data, err := os.ReadFile(validationFixturePath(t))
	if err != nil {
		t.Fatal(err)
	}
	var fixture validationFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	for _, test := range fixture.Validation.Cases {
		t.Run(test.Name, func(t *testing.T) {
			value, callErr := runValidationCase(test.Name)
			if test.OK {
				if callErr != nil {
					t.Fatalf("unexpected error: %v", callErr)
				}
				assertJSONEqual(t, value, test.Value)
				return
			}
			if callErr == nil {
				t.Fatalf("expected %s: %s", test.ErrorType, test.Error)
			}
			if callErr.Error() != test.Error {
				t.Fatalf("error = %q, want %q", callErr.Error(), test.Error)
			}
		})
	}
}

func runValidationCase(name string) (any, error) {
	switch name {
	case "validate_chroot_name":
		return ChrootName("androidos")
	case "validate_chroot_name_invalid_path":
		return ChrootName("../bad")
	case "validate_chroot_name_non_string":
		return ChrootName(7)
	case "validate_snapshot_name":
		return SnapshotName("pre-upgrade_1")
	case "validate_catalog_name":
		return CatalogName("desktop.dev")
	case "validate_service_name":
		return ServiceName("sshd@work.service:unit")
	case "validate_username":
		return Username("mike")
	case "validate_username_invalid":
		return Username("Mike")
	case "strict_bool":
		return StrictBool(false, "enabled")
	case "strict_bool_integer":
		return StrictBool(1, "enabled")
	case "bounded_int":
		return BoundedInt(3, "limit", 1, 5)
	case "bounded_int_bool":
		return BoundedInt(true, "limit", 1, 5)
	case "bounded_int_range":
		return BoundedInt(9, "limit", 1, 5)
	case "strict_string_list":
		return StrictStringList([]any{" a ", "", "b"}, "items", true)
	case "strict_string_list_invalid":
		return StrictStringList([]any{"a", 2}, "items", true)
	case "unique_catalog_names":
		return UniqueCatalogNames([]any{"one", "two"}, "")
	case "unique_catalog_names_duplicate":
		return UniqueCatalogNames([]any{"one", "one"}, "")
	case "relative_path":
		return RelativeChrootPath("home/mike")
	case "relative_path_normalized_input":
		return RelativeChrootPath("a/./b")
	case "relative_path_parent":
		return RelativeChrootPath("a/../b")
	case "relative_path_absolute":
		return RelativeChrootPath("/root")
	case "safe_archive_name":
		return SafeArchiveName("backup.tar.zst")
	case "safe_archive_name_multiline":
		return SafeArchiveName("bad\nname")
	default:
		return nil, &unknownCaseError{name: name}
	}
}

type unknownCaseError struct{ name string }

func (err *unknownCaseError) Error() string { return "unknown validation fixture case: " + err.name }

func assertJSONEqual(t *testing.T, got, want any) {
	t.Helper()
	gotData, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	wantData, err := json.Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	var gotValue, wantValue any
	if err := json.Unmarshal(gotData, &gotValue); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(wantData, &wantValue); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(gotValue, wantValue) {
		t.Fatalf("value = %s, want %s", gotData, wantData)
	}
}
