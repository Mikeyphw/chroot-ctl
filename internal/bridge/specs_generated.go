package bridge

import "sort"

type OperationSpec struct {
	Name          string              `json:"name"`
	Mode          string              `json:"mode"`
	Description   string              `json:"description"`
	Destructive   bool                `json:"destructive"`
	LockScope     string              `json:"lockScope"`
	PayloadFields map[string]struct{} `json:"-"`
}

func fieldSet(values ...string) map[string]struct{} {
	out := make(map[string]struct{}, len(values))
	for _, v := range values {
		out[v] = struct{}{}
	}
	return out
}

var orderedSpecs = []OperationSpec{
	{Name: "system.dashboard", Mode: "query", Description: "Return native dashboard state", Destructive: false, LockScope: "none", PayloadFields: fieldSet("details", "name", "tail")},
	{Name: "system.status", Mode: "query", Description: "Return status checks for one chroot", Destructive: false, LockScope: "none", PayloadFields: fieldSet("details", "name")},
	{Name: "system.doctor", Mode: "query", Description: "Return doctor checks for one chroot", Destructive: false, LockScope: "none", PayloadFields: fieldSet("name")},
	{Name: "chroots.list", Mode: "query", Description: "List registered chroots", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "chroots.get", Mode: "query", Description: "Return one registered chroot", Destructive: false, LockScope: "none", PayloadFields: fieldSet("name")},
	{Name: "storage.status", Mode: "query", Description: "Return structured storage status for one chroot", Destructive: false, LockScope: "none", PayloadFields: fieldSet("name")},
	{Name: "install.form", Mode: "query", Description: "Return native install form state", Destructive: false, LockScope: "none", PayloadFields: fieldSet("distro", "name")},
	{Name: "snapshots.list", Mode: "query", Description: "List snapshots for one or all chroots", Destructive: false, LockScope: "none", PayloadFields: fieldSet("limit", "name")},
	{Name: "users.list", Mode: "query", Description: "List chroot users", Destructive: false, LockScope: "none", PayloadFields: fieldSet("name")},
	{Name: "users.get", Mode: "query", Description: "Return one chroot user with UID/GID status", Destructive: false, LockScope: "none", PayloadFields: fieldSet("name", "username")},
	{Name: "services.list", Mode: "query", Description: "List chroot service units", Destructive: false, LockScope: "none", PayloadFields: fieldSet("name")},
	{Name: "services.get", Mode: "query", Description: "Return service status and journal", Destructive: false, LockScope: "none", PayloadFields: fieldSet("chroot", "name", "service", "serviceName", "tail", "unit")},
	{Name: "services.journal", Mode: "query", Description: "Return service journal with status context", Destructive: false, LockScope: "none", PayloadFields: fieldSet("chroot", "name", "service", "serviceName", "tail", "unit")},
	{Name: "logs.list", Mode: "query", Description: "Return bounded chrootctl log entries for one chroot", Destructive: false, LockScope: "none", PayloadFields: fieldSet("level", "name", "tail")},
	{Name: "operations.list", Mode: "query", Description: "List persistent operation records", Destructive: false, LockScope: "none", PayloadFields: fieldSet("limit", "name")},
	{Name: "operations.get", Mode: "query", Description: "Return one persistent operation with events", Destructive: false, LockScope: "none", PayloadFields: fieldSet("id", "operationId", "operation_id")},
	{Name: "install.preview", Mode: "preview", Description: "Preview a native install request", Destructive: false, LockScope: "none", PayloadFields: fieldSet("addons", "arch", "desktop", "distro", "forcePhase", "force_phase", "mirror", "name", "phase", "preset", "profile", "release", "repair", "resume", "tools", "username", "version")},
	{Name: "chroots.lifecycle.preview", Mode: "preview", Description: "Preview chroot lifecycle mutation", Destructive: false, LockScope: "none", PayloadFields: fieldSet("action", "name")},
	{Name: "chroots.remove", Mode: "preview", Description: "Preview removal without mutating data", Destructive: true, LockScope: "target", PayloadFields: fieldSet()},
	{Name: "chroots.export", Mode: "preview", Description: "Preview a chroot export", Destructive: false, LockScope: "none", PayloadFields: fieldSet("archive", "name")},
	{Name: "snapshots.preview", Mode: "preview", Description: "Preview snapshot create/restore/export", Destructive: true, LockScope: "none", PayloadFields: fieldSet("action", "archive", "name", "snapshot", "snapshotName", "snapshot_name")},
	{Name: "users.preview", Mode: "preview", Description: "Preview chroot user mutation", Destructive: true, LockScope: "target", PayloadFields: fieldSet("action", "deleteHome", "enabled", "fixOwnership", "name", "shell", "sudo", "username")},
	{Name: "services.preview", Mode: "preview", Description: "Preview service mutation", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "chroot", "name", "service", "serviceName", "target", "unit")},
	{Name: "catalog.tools", Mode: "query", Description: "List native tool catalog entries", Destructive: false, LockScope: "none", PayloadFields: fieldSet("category", "distro", "name", "q", "query", "targetName")},
	{Name: "catalog.addons", Mode: "query", Description: "List native add-on catalog entries", Destructive: false, LockScope: "none", PayloadFields: fieldSet("category", "distro", "name", "q", "query", "targetName")},
	{Name: "catalog.search", Mode: "query", Description: "Search native catalog entries", Destructive: false, LockScope: "none", PayloadFields: fieldSet("category", "distro", "kind", "name", "q", "query", "targetName")},
	{Name: "packages.inventory", Mode: "query", Description: "Return package inventory for one chroot", Destructive: false, LockScope: "none", PayloadFields: fieldSet("limit", "name")},
	{Name: "packages.compare", Mode: "query", Description: "Compare package inventories between chroots", Destructive: false, LockScope: "none", PayloadFields: fieldSet("left", "leftName", "right", "rightName")},
	{Name: "transfer.inspect_import", Mode: "query", Description: "Inspect a staged import archive", Destructive: false, LockScope: "none", PayloadFields: fieldSet("archive", "password", "path")},
	{Name: "artifacts.list", Mode: "query", Description: "List managed transfer artifacts", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "artifacts.cleanup_preview", Mode: "preview", Description: "Preview managed transfer artifact cleanup", Destructive: true, LockScope: "none", PayloadFields: fieldSet("artifactId", "artifact_id", "deleteAll", "delete_all", "path")},
	{Name: "transfer.artifact_root", Mode: "query", Description: "Return the managed transfer artifact root shared by Python and Android", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "catalog.preview", Mode: "preview", Description: "Preview applying tools or add-ons", Destructive: false, LockScope: "none", PayloadFields: fieldSet("entries", "entry", "kind", "name", "names")},
	{Name: "transfer.import_preview", Mode: "preview", Description: "Preview importing a staged archive", Destructive: false, LockScope: "none", PayloadFields: fieldSet("archive", "conflict", "name", "password", "path")},
	{Name: "transfer.preview_export", Mode: "preview", Description: "Preview exporting a chroot archive", Destructive: false, LockScope: "none", PayloadFields: fieldSet("archive", "name", "password")},
	{Name: "system.runtime", Mode: "query", Description: "Return native system runtime and host readiness", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "system.module_status", Mode: "query", Description: "Return Magisk/KernelSU module status", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "support.preview", Mode: "preview", Description: "Preview sanitized support bundle export", Destructive: false, LockScope: "none", PayloadFields: fieldSet("archive")},
	{Name: "system.module_build_preview", Mode: "preview", Description: "Preview Magisk/KernelSU module build", Destructive: false, LockScope: "none", PayloadFields: fieldSet("allInstalled", "all_installed", "archive", "startupTargets")},
	{Name: "repair.preview", Mode: "preview", Description: "Preview registry repair plan", Destructive: true, LockScope: "none", PayloadFields: fieldSet("decisions")},
	{Name: "cleanup.temp_preview", Mode: "preview", Description: "Preview managed temporary artifact cleanup", Destructive: true, LockScope: "none", PayloadFields: fieldSet("artifactId", "artifact_id", "deleteAll", "delete_all", "path")},
	{Name: "debug.probes", Mode: "query", Description: "Run chroot debug workbench probes", Destructive: false, LockScope: "none", PayloadFields: fieldSet("group")},
	{Name: "debug.timeline", Mode: "query", Description: "Return debug audit timeline", Destructive: false, LockScope: "none", PayloadFields: fieldSet("limit")},
	{Name: "smoke.plan", Mode: "query", Description: "Return real-device smoke suite plan", Destructive: false, LockScope: "none", PayloadFields: fieldSet("includeOptional", "include_optional", "name", "scope", "target")},
	{Name: "smoke.preview", Mode: "preview", Description: "Preview the real-device smoke suite before execution", Destructive: false, LockScope: "none", PayloadFields: fieldSet("includeOptional", "include_optional", "name", "scope", "target")},
	{Name: "smoke.report", Mode: "query", Description: "Return latest real-device smoke operation report", Destructive: false, LockScope: "none", PayloadFields: fieldSet("limit", "name", "target")},
	{Name: "smoke.last_result", Mode: "query", Description: "Return latest smoke result and support handoff guidance", Destructive: false, LockScope: "none", PayloadFields: fieldSet("limit")},
	{Name: "release.readiness", Mode: "query", Description: "Return native release readiness checklist", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "final.preflight", Mode: "query", Description: "Return final native release preflight summary", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "final.packaging_audit", Mode: "query", Description: "Return final module/package audit summary", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "final.no_webui_regression", Mode: "query", Description: "Return final WebUI retirement regression summary", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "final.release_seal", Mode: "query", Description: "Return final operational release seal", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "operations.retry", Mode: "operation", Description: "Retry a recorded operation after redaction checks", Destructive: true, LockScope: "global", PayloadFields: fieldSet("id", "mode", "operationId", "operation_id")},
	{Name: "system.refresh", Mode: "operation", Description: "Persist and stream a complete read-only refresh", Destructive: false, LockScope: "none", PayloadFields: fieldSet()},
	{Name: "smoke.run", Mode: "operation", Description: "Run real-device read-only operational smoke suite", Destructive: false, LockScope: "global", PayloadFields: fieldSet("includeOptional", "include_optional", "name", "scope", "target")},
	{Name: "smoke.result.persist", Mode: "operation", Description: "Persist latest smoke result into a managed JSON artifact", Destructive: false, LockScope: "global", PayloadFields: fieldSet("archive", "limit")},
	{Name: "smoke.result.export", Mode: "operation", Description: "Export latest smoke result evidence into a managed JSON artifact", Destructive: false, LockScope: "global", PayloadFields: fieldSet("archive", "limit")},
	{Name: "smoke.failure.bundle", Mode: "operation", Description: "Create support bundle linked to the latest smoke failure", Destructive: false, LockScope: "global", PayloadFields: fieldSet("archive", "limit")},
	{Name: "install.run", Mode: "operation", Description: "Run the native install flow", Destructive: false, LockScope: "global", PayloadFields: fieldSet("addons", "arch", "desktop", "distro", "forcePhase", "force_phase", "mirror", "name", "phase", "preset", "profile", "release", "repair", "resume", "tools", "username", "version")},
	{Name: "chroots.start", Mode: "operation", Description: "Start a chroot session", Destructive: false, LockScope: "target", PayloadFields: fieldSet("login", "name", "rootLogin", "root_login")},
	{Name: "chroots.restart", Mode: "operation", Description: "Restart a chroot session", Destructive: false, LockScope: "target", PayloadFields: fieldSet("login", "name", "rootLogin", "root_login")},
	{Name: "chroots.upgrade", Mode: "operation", Description: "Upgrade a chroot after preview", Destructive: true, LockScope: "target", PayloadFields: fieldSet("name", "username")},
	{Name: "chroots.remove.execute", Mode: "operation", Description: "Remove a chroot after typed confirmation", Destructive: true, LockScope: "target", PayloadFields: fieldSet("confirmName", "confirmation", "name")},
	{Name: "snapshots.create", Mode: "operation", Description: "Create a chroot snapshot", Destructive: false, LockScope: "target", PayloadFields: fieldSet("description", "name", "snapshot", "snapshotName", "snapshot_name")},
	{Name: "snapshots.restore", Mode: "operation", Description: "Restore a chroot snapshot", Destructive: true, LockScope: "target", PayloadFields: fieldSet("confirmName", "confirmation", "name", "snapshot", "snapshotName", "snapshot_name")},
	{Name: "snapshots.export", Mode: "operation", Description: "Export a chroot snapshot", Destructive: false, LockScope: "target", PayloadFields: fieldSet("archive", "name", "snapshot", "snapshotName", "snapshot_name")},
	{Name: "users.add", Mode: "operation", Description: "Add a chroot user", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "name", "shell", "sudo", "username")},
	{Name: "users.remove", Mode: "operation", Description: "Remove a chroot user after typed confirmation", Destructive: true, LockScope: "target", PayloadFields: fieldSet("action", "confirmUsername", "confirmation", "deleteHome", "name", "username")},
	{Name: "users.sync_uid_gid", Mode: "operation", Description: "Sync UID/GID for a chroot user", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "fixOwnership", "name", "username")},
	{Name: "users.set_shell", Mode: "operation", Description: "Set a chroot user shell", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "name", "shell", "username")},
	{Name: "users.set_sudo", Mode: "operation", Description: "Enable or disable sudo for a chroot user", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "enabled", "name", "sudo", "username")},
	{Name: "users.set_password", Mode: "operation", Description: "Set a chroot user password with redacted request data", Destructive: true, LockScope: "target", PayloadFields: fieldSet("action", "confirmPassword", "confirmUsername", "confirmation", "name", "password", "username")},
	{Name: "services.start", Mode: "operation", Description: "Start a chroot service", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "chroot", "name", "service", "serviceName", "target", "unit")},
	{Name: "services.stop", Mode: "operation", Description: "Stop a chroot service", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "chroot", "name", "service", "serviceName", "target", "unit")},
	{Name: "services.restart", Mode: "operation", Description: "Restart a chroot service", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "chroot", "name", "service", "serviceName", "target", "unit")},
	{Name: "services.enable", Mode: "operation", Description: "Enable a chroot service", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "chroot", "name", "service", "serviceName", "target", "unit")},
	{Name: "services.disable", Mode: "operation", Description: "Disable a chroot service", Destructive: false, LockScope: "target", PayloadFields: fieldSet("action", "chroot", "name", "service", "serviceName", "target", "unit")},
	{Name: "catalog.apply", Mode: "operation", Description: "Apply native tool or add-on catalog entries", Destructive: false, LockScope: "target", PayloadFields: fieldSet("entries", "entry", "kind", "name", "names")},
	{Name: "transfer.import", Mode: "operation", Description: "Import a staged chroot archive", Destructive: false, LockScope: "global", PayloadFields: fieldSet("archive", "conflict", "name", "password", "path", "postImport", "post_import")},
	{Name: "transfer.export", Mode: "operation", Description: "Export a chroot archive to managed artifacts", Destructive: false, LockScope: "target", PayloadFields: fieldSet("archive", "name", "password")},
	{Name: "artifacts.cleanup", Mode: "operation", Description: "Clean managed transfer artifacts", Destructive: true, LockScope: "global", PayloadFields: fieldSet("artifactId", "artifact_id", "deleteAll", "delete_all", "path")},
	{Name: "support.bundle", Mode: "operation", Description: "Export sanitized support bundle", Destructive: false, LockScope: "global", PayloadFields: fieldSet("archive")},
	{Name: "system.module_build", Mode: "operation", Description: "Build Magisk/KernelSU module artifact", Destructive: false, LockScope: "global", PayloadFields: fieldSet("allInstalled", "all_installed", "archive", "startupTargets")},
	{Name: "repair.apply", Mode: "operation", Description: "Apply selected registry repair plan", Destructive: true, LockScope: "global", PayloadFields: fieldSet("decisions")},
	{Name: "cleanup.temp", Mode: "operation", Description: "Clean managed temporary artifacts", Destructive: true, LockScope: "global", PayloadFields: fieldSet("artifactId", "artifact_id", "deleteAll", "delete_all", "path")},
	{Name: "debug.export", Mode: "operation", Description: "Export debug workbench evidence bundle", Destructive: false, LockScope: "global", PayloadFields: fieldSet("archive", "group", "limit")},
}

var Specs = func() map[string]OperationSpec {
	out := make(map[string]OperationSpec, len(orderedSpecs))
	for _, spec := range orderedSpecs {
		out[spec.Name] = spec
	}
	return out
}()

func Capabilities() []map[string]any {
	out := make([]map[string]any, 0, len(orderedSpecs))
	for _, s := range orderedSpecs {
		out = append(out, map[string]any{"name": s.Name, "mode": s.Mode, "description": s.Description, "destructive": s.Destructive, "lockScope": s.LockScope})
	}
	return out
}

var previewContractFields = map[string]struct{}{"previewId": {}, "payloadHash": {}, "resourceRevision": {}}

func Resolve(req Request, expectedMode string) (OperationSpec, error) {
	spec, ok := Specs[req.Operation]
	if !ok {
		return OperationSpec{}, protocolError("UNSUPPORTED_OPERATION", "Unsupported operation: "+req.Operation, nil)
	}
	if spec.Mode != expectedMode {
		return OperationSpec{}, protocolError("OPERATION_MODE_MISMATCH", "Operation "+req.Operation+" is a "+spec.Mode+" operation, not "+expectedMode, nil)
	}
	// Python protocol-v1 has a historical allowlist typo for chroots.remove:
	// the preview handler accepts payload.name while the metadata exporter reports
	// an empty field set. Preserve runtime compatibility until a protocol bump.
	if req.Operation == "chroots.remove" {
		return spec, nil
	}
	unknown := []string{}
	for key := range req.Payload {
		if _, ok := spec.PayloadFields[key]; ok {
			continue
		}
		if _, ok := previewContractFields[key]; ok {
			continue
		}
		unknown = append(unknown, key)
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return OperationSpec{}, protocolError("UNKNOWN_PAYLOAD_FIELD", "Unsupported field(s) for "+req.Operation, map[string]any{"fields": unknown})
	}
	return spec, nil
}
