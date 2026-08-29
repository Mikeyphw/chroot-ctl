package redaction

import "testing"

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
