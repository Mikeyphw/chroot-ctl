package bridge

import "testing"

func TestPostCUXReleaseReadinessResponseSchemaMatchesRuntimeContract(t *testing.T) {
	schema := ResponseSchemaFor("release.readiness")
	if schema.Kind != "object" {
		t.Fatalf("release.readiness kind = %q, want object", schema.Kind)
	}
	fields := make(map[string]bool, len(schema.Fields))
	for _, field := range schema.Fields {
		fields[field] = true
	}
	for _, want := range []string{
		"schemaVersion", "evidencePath", "evidencePresent", "evidenceProblem",
		"generatedAt", "validationRunId", "sourceCommit", "sourceTree", "checks",
		"passCount", "failCount", "pendingCount", "ready",
	} {
		if !fields[want] {
			t.Fatalf("release.readiness schema missing %q: %#v", want, schema.Fields)
		}
	}
	if fields["summary"] {
		t.Fatalf("release.readiness schema still advertises retired summary field: %#v", schema.Fields)
	}
}
