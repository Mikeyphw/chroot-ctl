package redaction

import (
	"strings"
	"testing"
)

func TestRedactSecrets(t *testing.T) {
	got := Value(map[string]any{"password": "secret", "nested": map[string]any{"access_token": "abc", "message": "Bearer secret-value"}}).(map[string]any)
	if got["password"] != "<redacted>" {
		t.Fatalf("password=%v", got["password"])
	}
	nested := got["nested"].(map[string]any)
	if nested["access_token"] != "<redacted>" || nested["message"] != "Bearer <redacted>" {
		t.Fatalf("nested=%#v", nested)
	}
}

func TestCHR16RedactsCommonSecretForms(t *testing.T) {
	input := "Authorization: Bearer abc.def token=plain password = hunter2 https://user:pass@example.com ghp_012345678901234567890123456789012345 AKIAABCDEFGHIJKLMNOP"
	got := String(input)
	for _, leak := range []string{"abc.def", "hunter2", "user:pass", "ghp_012345", "AKIAABCDEFGHIJKLMNOP"} {
		if strings.Contains(got, leak) {
			t.Fatalf("secret %q leaked in %q", leak, got)
		}
	}
}
