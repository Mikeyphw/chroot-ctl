package bridge

// ResponseSchema documents the object/array shape returned by bridge data for
// Android. It is deliberately small and wire-facing: Android uses it for API
// reference/capability negotiation, and repoctl validates the operations most
// likely to drift between backend and UI workspaces.
type ResponseSchema struct {
	Kind            string
	Fields          []string
	CapabilityTags  []string
	RequiresPreview bool
}

var responseSchemas = map[string]ResponseSchema{
	"install.form":            {Kind: "object", Fields: []string{"schemaVersion", "distros", "architectures", "presets", "profiles", "desktops", "mirrors", "defaults"}, CapabilityTags: []string{"form"}},
	"chroots.list":            {Kind: "array", Fields: []string{"name", "distro", "releaseName", "phase", "installed", "path"}, CapabilityTags: []string{"list"}},
	"chroots.get":             {Kind: "object", Fields: []string{"name", "distro", "releaseName", "phase", "installed", "path"}},
	"system.runtime":          {Kind: "object", Fields: []string{"lifecycle", "host", "crossArch", "module"}, CapabilityTags: []string{"readiness"}},
	"system.module_status":    {Kind: "object", Fields: []string{"status", "runtimeKind", "modulePath", "warnings"}, CapabilityTags: []string{"module"}},
	"logs.list":               {Kind: "object", Fields: []string{"name", "logFile", "level", "tail", "count", "truncated", "readError", "refreshedAt", "entries"}, CapabilityTags: []string{"logs", "workspace"}},
	"operations.find_request": {Kind: "object", Fields: []string{"requestId", "operationId", "found", "state", "kind"}, CapabilityTags: []string{"operations", "recovery"}},
	"support.preview":         {Kind: "preview", Fields: []string{"ok", "kind", "archive", "warnings", "blocking", "confirm"}, CapabilityTags: []string{"support", "evidence"}},
	"support.bundle":          {Kind: "operation", Fields: []string{"archive", "artifact", "checksum", "included"}, CapabilityTags: []string{"support", "evidence"}, RequiresPreview: true},
	"repair.preview":          {Kind: "preview", Fields: []string{"ok", "items", "decisions", "selected", "blocking", "warnings"}, CapabilityTags: []string{"repair"}},
	"debug.probes":            {Kind: "object", Fields: []string{"schemaVersion", "group", "probes", "count", "generatedAt"}, CapabilityTags: []string{"debug", "probes"}},
	"debug.timeline":          {Kind: "object", Fields: []string{"schemaVersion", "events", "count", "limit"}, CapabilityTags: []string{"debug", "timeline"}},
	"debug.export":            {Kind: "operation", Fields: []string{"archive", "artifact", "checksum", "included"}, CapabilityTags: []string{"debug", "evidence"}},
	"smoke.plan":              {Kind: "object", Fields: []string{"schemaVersion", "ok", "target", "scope", "includeOptional", "steps", "destructive"}, CapabilityTags: []string{"smoke", "plan"}},
	"smoke.preview":           {Kind: "preview", Fields: []string{"schemaVersion", "ok", "target", "scope", "includeOptional", "steps", "destructive"}, CapabilityTags: []string{"smoke", "preview"}},
	"smoke.report":            {Kind: "object", Fields: []string{"schemaVersion", "ok", "status", "operations", "count", "failed", "latest"}, CapabilityTags: []string{"smoke", "report"}},
	"smoke.last_result":       {Kind: "object", Fields: []string{"schemaVersion", "ok", "status", "operation", "result", "recovery", "nextSteps"}, CapabilityTags: []string{"smoke", "result"}},
	"smoke.result.persist":    {Kind: "operation", Fields: []string{"archive", "artifact", "result"}, CapabilityTags: []string{"smoke", "evidence"}},
	"smoke.result.export":     {Kind: "operation", Fields: []string{"archive", "artifact", "result"}, CapabilityTags: []string{"smoke", "evidence"}},
	"smoke.failure.bundle":    {Kind: "operation", Fields: []string{"archive", "artifact", "result"}, CapabilityTags: []string{"smoke", "evidence"}},
	"release.readiness":       {Kind: "object", Fields: []string{"ready", "checks", "summary"}, CapabilityTags: []string{"release"}},
	"final.release_seal":      {Kind: "object", Fields: []string{"ok", "preflight", "packaging", "noWebui"}, CapabilityTags: []string{"release", "seal"}},
}

// ResponseSchemaFor returns a non-empty response contract for every operation.
func ResponseSchemaFor(operation string) ResponseSchema {
	if schema, ok := responseSchemas[operation]; ok {
		return schema
	}
	spec, ok := Specs[operation]
	if !ok {
		return ResponseSchema{Kind: "unknown", Fields: []string{}, CapabilityTags: []string{"unknown"}}
	}
	kind := "object"
	switch spec.Mode {
	case "operation":
		kind = "operation"
	case "preview":
		kind = "preview"
	}
	return ResponseSchema{Kind: kind, Fields: []string{}, CapabilityTags: []string{spec.Mode}}
}
