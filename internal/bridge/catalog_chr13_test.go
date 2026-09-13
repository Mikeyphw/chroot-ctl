package bridge

import (
	"testing"

	"chrootctl/internal/catalog"
)

func TestCHR13EntryPayloadIncludesRiskAndState(t *testing.T) {
	payload := entryPayload(catalog.Entry{
		Kind: "tool", Name: "sync-uid", Description: "blocked", Script: "sync-uid.sh", Source: "builtin",
		ScriptSHA256: "abc123", RiskLevel: "blocked", State: "blocked", StateReason: "host-managed",
		Rollback: "manual", Risks: []string{"identity-mutation"}, Requires: []string{"bash"},
		Destructive: true, RequiresConfirmation: false,
	})
	checks := map[string]any{
		"script_sha256":         "abc123",
		"scriptSha256":          "abc123",
		"risk_level":            "blocked",
		"riskLevel":             "blocked",
		"state":                 "blocked",
		"state_reason":          "host-managed",
		"stateReason":           "host-managed",
		"destructive":           true,
		"requires_confirmation": false,
		"requiresConfirmation":  false,
	}
	for key, want := range checks {
		if got := payload[key]; got != want {
			t.Fatalf("%s=%v want %v", key, got, want)
		}
	}
}
