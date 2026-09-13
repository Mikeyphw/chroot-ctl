package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateBridgeProtocolV2Convergence keeps CHR17 executable instead of prose-only.
// It seals the bridge/API convergence layer: capabilities expose response shapes,
// debug timeline is no longer returned as a bare array, debug probes retain their
// raw result payload, smoke report/result mappings are not forced through generic
// preview text, and Android preserves envelope error details for actionable UI.
func ValidateBridgeProtocolV2Convergence(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR17 read %s: %w", rel, err)
		}
		return string(b), nil
	}
	mustContain := func(rel string, tokens ...string) error {
		text, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if !strings.Contains(text, token) {
				return fmt.Errorf("CHR17 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	if err := mustContain("internal/bridge/response_schemas.go",
		"type ResponseSchema struct",
		"debug.timeline",
		"responseSchemas",
		"ResponseSchemaFor",
	); err != nil {
		return err
	}
	if err := mustContain("internal/bridge/specs_generated.go",
		"ResponseKind",
		"responseFields",
		"capabilityTags",
		"requiresPreview",
	); err != nil {
		return err
	}
	if err := mustContain("internal/bridge/backend.go",
		"normalizeTimelineEvents(events)",
		`"events": normalizeTimelineEvents(events)`,
		"debugProbe(\"runtime\", \"lifecycle\"",
		`"schemaVersion": 2`,
		`"recovery": recovery`,
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/protocol/BridgeModels.kt",
		"responseKind: String",
		"responseFields: List<String>",
		"capabilityTags: List<String>",
		"errorDetails: JSONObject?",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt",
		"toSmokePlanSummary",
		"toSmokeReportSummary",
		"toSmokeLastResultSummary",
		"rawResult = result?.toString().orEmpty()",
		"capability.responseKind",
	); err != nil {
		return err
	}
	if err := mustContain("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt",
		"details: List<String>",
		"rawResult: String",
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/roadmap-coverage.json",
		`"id": "CHR17"`,
		`"title": "Bridge protocol V2 convergence"`,
		`"ownerOverlay": "CHR17"`,
		`"status": "implemented"`,
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/CHR17_BRIDGE_PROTOCOL_V2_CONVERGENCE.md", "Bridge protocol V2 convergence", "ValidateBridgeProtocolV2Convergence"); err != nil {
		return err
	}
	return nil
}
