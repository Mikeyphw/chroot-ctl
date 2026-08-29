package apperrors

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"
)

type errorFixture struct {
	Errors map[string]map[string]any `json:"errors"`
}

func fixturePath(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "migration", "contracts", "v1", "foundations.json"))
}

func TestErrorPayloadParity(t *testing.T) {
	data, err := os.ReadFile(fixturePath(t))
	if err != nil {
		t.Fatal(err)
	}
	var fixture errorFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}

	href := "https://example.invalid/docs"
	app := AppError{
		Code:       "config_invalid",
		Title:      "Invalid configuration",
		Message:    "The configuration is invalid.",
		Details:    map[string]any{"field": "username"},
		Hints:      []string{"Use a lowercase username."},
		Actions:    []ErrorAction{{Label: "Open docs", Href: &href}},
		StatusCode: 422,
	}.ToResponse().HTTPPayload()
	assertJSONEquivalent(t, app, fixture.Errors["appError"])
	assertJSONEquivalent(t, FromHTTPException(404, nil).HTTPPayload(), fixture.Errors["http404"])

	command := "chrootctl status"
	response := FromHTTPException(422, map[string]any{
		"code":      "bad_request",
		"message":   "bad payload",
		"details":   map[string]any{"field": "name"},
		"hints":     []any{"Pick another name."},
		"actions":   []any{map[string]any{"label": "Retry", "command": command}},
		"retryable": true,
	})
	assertJSONEquivalent(t, response.HTTPPayload(), fixture.Errors["http422"])
}

func assertJSONEquivalent(t *testing.T, got, want any) {
	t.Helper()
	gotBytes, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	wantBytes, err := json.Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	var gotValue, wantValue any
	if err := json.Unmarshal(gotBytes, &gotValue); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(wantBytes, &wantValue); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(gotValue, wantValue) {
		t.Fatalf("payload mismatch\n got: %s\nwant: %s", gotBytes, wantBytes)
	}
}
