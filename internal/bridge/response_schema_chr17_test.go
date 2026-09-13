package bridge

import "testing"

func TestCHR17CapabilitiesExposeResponseSchemas(t *testing.T) {
	caps := Capabilities()
	byName := map[string]map[string]any{}
	for _, cap := range caps {
		byName[asString(cap["name"])] = cap
	}
	for _, tc := range []struct {
		operation string
		kind      string
		field     string
	}{
		{"debug.timeline", "object", "events"},
		{"debug.probes", "object", "probes"},
		{"smoke.report", "object", "operations"},
		{"smoke.last_result", "object", "recovery"},
		{"support.bundle", "operation", "artifact"},
	} {
		cap := byName[tc.operation]
		if cap == nil {
			t.Fatalf("missing capability %s", tc.operation)
		}
		if cap["responseKind"] != tc.kind {
			t.Fatalf("%s responseKind=%v want %s", tc.operation, cap["responseKind"], tc.kind)
		}
		fields, ok := cap["responseFields"].([]string)
		if !ok {
			t.Fatalf("%s responseFields type=%T", tc.operation, cap["responseFields"])
		}
		found := false
		for _, f := range fields {
			found = found || f == tc.field
		}
		if !found {
			t.Fatalf("%s responseFields=%v missing %s", tc.operation, fields, tc.field)
		}
	}
}

func TestCHR17ContractSpecsCarryDefensiveResponseSchemas(t *testing.T) {
	specs := ContractSpecs()
	var timeline *OperationSpec
	for i := range specs {
		if specs[i].Name == "debug.timeline" {
			timeline = &specs[i]
			break
		}
	}
	if timeline == nil {
		t.Fatal("debug.timeline not found")
	}
	if timeline.ResponseKind != "object" {
		t.Fatalf("response kind=%q", timeline.ResponseKind)
	}
	if len(timeline.ResponseFields) == 0 || timeline.ResponseFields[0] != "schemaVersion" {
		t.Fatalf("response fields=%v", timeline.ResponseFields)
	}
	timeline.ResponseFields[0] = "mutated"
	again := ContractSpecs()
	for _, spec := range again {
		if spec.Name == "debug.timeline" && spec.ResponseFields[0] == "mutated" {
			t.Fatal("ContractSpecs leaked mutable response field slice")
		}
	}
}
