package cli

import (
	"encoding/json"
	"strings"
	"testing"

	"chrootctl/internal/apperrors"
)

func TestCHR23ErrorResponseRedactsEveryUserVisibleField(t *testing.T) {
	href := "https://user:pass@example.invalid/recover?token=abc123"
	command := "chrootctl users password alice --password=hunter2"
	response := appErrorResponse(apperrors.AppError{
		Code:    "sensitive_failure",
		Title:   "token=title-secret",
		Message: "password=message-secret",
		Details: map[string]any{
			"password": "detail-secret",
			"nested":   map[string]any{"message": "Bearer nested-secret"},
		},
		Hints: []string{"authorization: Bearer hint-secret"},
		Actions: []apperrors.ErrorAction{{
			Label:   "token=label-secret",
			Href:    &href,
			Command: &command,
		}},
	})

	raw, err := json.Marshal(response)
	if err != nil {
		t.Fatal(err)
	}
	text := string(raw)
	for _, secret := range []string{
		"title-secret",
		"message-secret",
		"detail-secret",
		"nested-secret",
		"hint-secret",
		"label-secret",
		"user:pass",
		"abc123",
		"hunter2",
	} {
		if strings.Contains(text, secret) {
			t.Fatalf("secret %q leaked in response %s", secret, text)
		}
	}
	if !strings.Contains(text, "redacted") {
		t.Fatalf("response did not contain redaction marker: %s", text)
	}
}
