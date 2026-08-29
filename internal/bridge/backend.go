package bridge

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"chrootctl/internal/catalog"
	"chrootctl/internal/model"
	"chrootctl/internal/operations"
	"chrootctl/internal/services"
	"chrootctl/internal/validation"
)

type Progress func(any) error
type Backend interface {
	State(context.Context) (any, error)
	Invoke(context.Context, string, string, map[string]any, Progress, func() bool) (any, error)
}

type ServicesBackend struct{ Services *services.Container }

func NewServicesBackend(s *services.Container) *ServicesBackend { return &ServicesBackend{Services: s} }
func (b *ServicesBackend) State(ctx context.Context) (any, error) {
	d, e := b.Services.System().Dashboard(ctx, "", true, 20)
	if e != nil {
		return nil, e
	}
	ops, e := b.Services.Operations.ListRecent(20, nil)
	if e != nil {
		return nil, e
	}
	return map[string]any{"dashboard": d, "operations": ops}, nil
}

func reqName(p map[string]any) (string, error) {
	v := strings.TrimSpace(asString(p["name"]))
	if v == "" {
		return "", protocolError("MISSING_CHROOT_NAME", "payload.name is required", nil)
	}
	x, e := validation.ChrootNameField(v, "payload.name")
	if e != nil {
		return "", protocolError("INVALID_CHROOT_NAME", e.Error(), nil)
	}
	return x, nil
}
func optText(p map[string]any, key string) string {
	if v, ok := p[key]; ok && v != nil {
		return strings.TrimSpace(asString(v))
	}
	return ""
}
func reqUser(p map[string]any) (string, error) {
	v := optText(p, "username")
	if v == "" {
		return "", protocolError("MISSING_USERNAME", "payload.username is required", nil)
	}
	x, e := validation.UsernameField(v, "payload.username")
	if e != nil {
		return "", protocolError("INVALID_USERNAME", e.Error(), nil)
	}
	return x, nil
}
func reqSnapshot(p map[string]any) (string, error) {
	v := optText(p, "snapshot")
	if v == "" {
		v = optText(p, "snapshotName")
	}
	if v == "" {
		v = optText(p, "snapshot_name")
	}
	if v == "" {
		return "", protocolError("MISSING_SNAPSHOT_NAME", "payload.snapshot is required", nil)
	}
	x, e := validation.SnapshotNameField(v, "payload.snapshot")
	if e != nil {
		return "", protocolError("INVALID_SNAPSHOT_NAME", e.Error(), nil)
	}
	return x, nil
}
func reqService(p map[string]any) (string, error) {
	v := optText(p, "service")
	if v == "" {
		v = optText(p, "serviceName")
	}
	if v == "" {
		v = optText(p, "unit")
	}
	if v == "" {
		return "", protocolError("MISSING_SERVICE", "payload.service is required", nil)
	}
	x, e := validation.ServiceNameField(v, "payload.service")
	if e != nil {
		return "", protocolError("INVALID_SERVICE", e.Error(), nil)
	}
	return x, nil
}
func optBool(p map[string]any, keys []string, d bool) (bool, error) {
	v, e := validation.OptionalBool(p, keys, d, "payload."+keys[0])
	if e != nil {
		return false, protocolError("INVALID_BOOLEAN", e.Error(), nil)
	}
	return v, nil
}
func bounded(p map[string]any, key string, d, min, max int64, code string) (int, error) {
	v, e := validation.OptionalBoundedInt(p, key, d, min, max)
	if e != nil {
		return 0, protocolError(code, e.Error(), nil)
	}
	return int(v), nil
}
func cancelled(c func() bool, msg string) error {
	if c != nil && c() {
		return fmt.Errorf("%w: %s", operations.ErrCancelled, msg)
	}
	return nil
}
func emit(progress Progress, v any) error {
	if progress == nil {
		return nil
	}
	return progress(v)
}
func asStringSlice(v any) []string {
	out := []string{}
	switch x := v.(type) {
	case []string:
		return append(out, x...)
	case []any:
		for _, i := range x {
			if s := strings.TrimSpace(asString(i)); s != "" {
				out = append(out, s)
			}
		}
	case string:
		for _, s := range strings.Split(x, ",") {
			if s = strings.TrimSpace(s); s != "" {
				out = append(out, s)
			}
		}
	}
	return out
}
func catalogKind(p map[string]any) (string, error) {
	k := strings.ToLower(optText(p, "kind"))
	if k == "" {
		k = "tool"
	}
	if k == "tools" {
		k = "tool"
	}
	if k == "addons" {
		k = "addon"
	}
	if k != "tool" && k != "addon" {
		return "", protocolError("INVALID_CATALOG_KIND", "Unsupported catalog kind: "+k, nil)
	}
	return k, nil
}
func catalogNames(p map[string]any) ([]string, error) {
	var raw any
	for _, k := range []string{"names", "entries", "entry"} {
		if v, ok := p[k]; ok {
			raw = v
			break
		}
	}
	if raw == nil {
		return []string{}, nil
	}
	names, e := validation.UniqueCatalogNames(raw, "payload.names")
	if e != nil {
		return nil, protocolError("INVALID_CATALOG_NAMES", e.Error(), nil)
	}
	return names, nil
}
func entryPayload(e catalog.Entry) map[string]any {
	sum := sha256.Sum256([]byte(e.ScriptText))
	return map[string]any{"kind": e.Kind, "name": e.Name, "description": e.Description, "distros": e.Distros, "categories": e.Categories, "script": e.Script, "version": e.Version, "risks": e.Risks, "rollback": e.Rollback, "requires": e.Requires, "scriptSha256": hex.EncodeToString(sum[:])}
}
func decisions(p map[string]any) ([]map[string]string, error) {
	raw, ok := p["decisions"]
	if !ok || raw == nil {
		return []map[string]string{}, nil
	}
	a, ok := raw.([]any)
	if !ok {
		return nil, protocolError("INVALID_REPAIR_DECISIONS", "payload.decisions must be an array", nil)
	}
	out := []map[string]string{}
	for _, v := range a {
		m, ok := v.(map[string]any)
		if !ok {
			return nil, protocolError("INVALID_REPAIR_DECISIONS", "each repair decision must be an object", nil)
		}
		out = append(out, map[string]string{"item_id": strings.TrimSpace(asString(m["item_id"])), "action": strings.TrimSpace(asString(m["action"]))})
	}
	return out, nil
}

func stringPtr(v string) *string {
	if strings.TrimSpace(v) == "" {
		return nil
	}
	x := v
	return &x
}
func installRequest(p map[string]any) model.InstallRequest {
	r := model.InstallRequest{
		Distro: optText(p, "distro"), Name: optText(p, "name"), Username: optText(p, "username"), Arch: optText(p, "arch"),
		Preset: stringPtr(optText(p, "preset")), Profile: stringPtr(optText(p, "profile")), Desktop: stringPtr(optText(p, "desktop")),
		Release: stringPtr(optText(p, "release")), Version: stringPtr(optText(p, "version")), Mirror: stringPtr(optText(p, "mirror")), Phase: stringPtr(optText(p, "phase")),
		Tools: asStringSlice(p["tools"]), Addons: asStringSlice(p["addons"]),
	}
	if r.Distro == "" {
		r.Distro = "ubuntu"
	}
	if r.Arch == "" {
		r.Arch = "arm64"
	}
	if r.Profile == nil {
		r.Profile = stringPtr("base")
	}
	if r.Desktop == nil {
		r.Desktop = stringPtr("none")
	}
	r.Resume, _ = optBool(p, []string{"resume"}, false)
	r.Repair, _ = optBool(p, []string{"repair"}, false)
	r.ForcePhase, _ = optBool(p, []string{"forcePhase", "force_phase"}, false)
	return r
}

func (b *ServicesBackend) Invoke(ctx context.Context, mode, op string, p map[string]any, progress Progress, isCancelled func() bool) (any, error) {
	switch mode {
	case "query":
		return b.query(ctx, op, p)
	case "preview":
		return b.preview(ctx, op, p)
	case "operation":
		return b.operation(ctx, op, p, progress, isCancelled)
	default:
		return nil, protocolError("INVALID_OPERATION_MODE", "Unsupported operation mode: "+mode, nil)
	}
}

func (b *ServicesBackend) query(ctx context.Context, op string, p map[string]any) (any, error) {
	s := b.Services
	switch op {
	case "system.dashboard":
		details, e := optBool(p, []string{"details"}, true)
		if e != nil {
			return nil, e
		}
		tail, e := bounded(p, "tail", 20, 0, 500, "INVALID_DASHBOARD_PAYLOAD")
		if e != nil {
			return nil, e
		}
		return s.System().Dashboard(ctx, optText(p, "name"), details, tail)
	case "system.status":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		d, e := optBool(p, []string{"details"}, true)
		if e != nil {
			return nil, e
		}
		return s.System().Status(ctx, n, d)
	case "system.doctor":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		return s.System().Doctor(ctx, n)
	case "chroots.list":
		return s.Chroots().List(ctx)
	case "chroots.get":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		return s.Chroots().Get(ctx, n)
	case "storage.status":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		return s.Chroots().StorageStatus(ctx, n)
	case "install.form":
		return s.Install().InstallFormState(ctx, optText(p, "name"), optText(p, "distro"))
	case "snapshots.list":
		lim, e := bounded(p, "limit", 100, 0, 500, "INVALID_SNAPSHOT_LIMIT")
		if e != nil {
			return nil, e
		}
		return s.Snapshots().List(ctx, optText(p, "name"), lim)
	case "users.list":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		return s.Users(n).List(ctx)
	case "users.get":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		u, e := reqUser(p)
		if e != nil {
			return nil, e
		}
		return s.Users(n).Show(ctx, u)
	case "services.list":
		rows, e := s.Services().List(ctx)
		if e != nil {
			return nil, e
		}
		n := optText(p, "name")
		if n == "" {
			return rows, nil
		}
		out := []map[string]string{}
		for _, r := range rows {
			if r["chroot"] == n {
				out = append(out, r)
			}
		}
		return out, nil
	case "services.get", "services.journal":
		unit, e := reqService(p)
		if e != nil {
			return nil, e
		}
		name := optText(p, "name")
		if name == "" {
			name = optText(p, "chroot")
		}
		tail, e := bounded(p, "tail", 120, 0, 500, "INVALID_SERVICE_TAIL")
		if e != nil {
			return nil, e
		}
		st, e := s.Services().Status(ctx, unit, name)
		if e != nil {
			return nil, e
		}
		logs, e := s.Services().Logs(ctx, unit, name, tail)
		if e != nil {
			return nil, e
		}
		return map[string]any{"status": st, "journal": logs}, nil
	case "logs.list":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		tail, e := bounded(p, "tail", 200, 0, 500, "INVALID_LOG_TAIL")
		if e != nil {
			return nil, e
		}
		if tail < 20 {
			tail = 20
		}
		level := strings.ToUpper(optText(p, "level"))
		if level != "" && level != "DEBUG" && level != "INFO" && level != "WARNING" && level != "ERROR" && level != "CRITICAL" {
			return nil, protocolError("INVALID_LOG_LEVEL", "payload.level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL", nil)
		}
		snap, e := s.System().Logs(ctx, n, tail, false, level, false)
		if e != nil {
			return nil, e
		}
		entries := []map[string]any{}
		for _, x := range snap.Entries {
			lv := ""
			if x.Level != nil {
				lv = *x.Level
			}
			entries = append(entries, map[string]any{"line": x.Line, "level": lv})
		}
		return map[string]any{"name": n, "logFile": snap.LogFile, "level": level, "tail": tail, "entries": entries}, nil
	case "operations.list":
		lim, e := bounded(p, "limit", 50, 0, 1000, "INVALID_OPERATION_LIMIT")
		if e != nil {
			return nil, e
		}
		var target *string
		if n := optText(p, "name"); n != "" {
			safe, e := validation.ChrootNameField(n, "payload.name")
			if e != nil {
				return nil, e
			}
			target = &safe
		}
		return s.Operations.ListRecent(lim, target)
	case "operations.get":
		id := optText(p, "operationId")
		if id == "" {
			id = optText(p, "operation_id")
		}
		if id == "" {
			id = optText(p, "id")
		}
		if id == "" {
			return nil, protocolError("MISSING_OPERATION_ID", "payload.operationId is required", nil)
		}
		return s.Operations.Get(id, 200)
	case "catalog.tools":
		q := copyMap(p)
		q["kind"] = "tool"
		return b.catalogList(ctx, q)
	case "catalog.addons":
		q := copyMap(p)
		q["kind"] = "addon"
		return b.catalogList(ctx, q)
	case "catalog.search":
		return b.catalogList(ctx, p)
	case "packages.inventory":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		lim, e := bounded(p, "limit", 500, 0, 5000, "INVALID_PACKAGE_LIMIT")
		if e != nil {
			return nil, e
		}
		items, e := s.Chroots().PackageInventory(ctx, n, lim)
		if e != nil {
			return nil, e
		}
		return map[string]any{"name": n, "count": len(items), "packages": items}, nil
	case "packages.compare":
		left := optText(p, "left")
		if left == "" {
			left = optText(p, "leftName")
		}
		right := optText(p, "right")
		if right == "" {
			right = optText(p, "rightName")
		}
		if left == "" || right == "" {
			return nil, protocolError("MISSING_CHROOT_NAME", "payload.left and payload.right are required", nil)
		}
		return s.Chroots().PackageDiff(ctx, left, right)
	case "transfer.inspect_import":
		a := optText(p, "archive")
		if a == "" {
			a = optText(p, "path")
		}
		if a == "" {
			return nil, protocolError("MISSING_ARCHIVE", "payload.archive is required", nil)
		}
		return s.Transfer().Inspect(ctx, a, optText(p, "password"))
	case "artifacts.list":
		return s.Registry.ListArtifacts(ctx, false, 500)
	case "transfer.artifact_root":
		return s.Transfer().ArtifactRoot(), nil
	case "system.runtime":
		return map[string]any{"lifecycle": s.Lifecycle().Status(), "host": s.Doctor().HostReadiness(ctx), "crossArch": s.Doctor().CrossArchReadiness(), "module": s.ModuleRuntime().Status()}, nil
	case "system.module_status":
		return s.ModuleRuntime().Status(), nil
	case "debug.probes":
		return b.debugProbes(ctx, optText(p, "group"))
	case "debug.timeline":
		lim, e := bounded(p, "limit", 100, 0, 500, "INVALID_TIMELINE_LIMIT")
		if e != nil {
			return nil, e
		}
		return s.Audit().Recent(ctx, lim)
	case "smoke.plan":
		return b.smokePlan(ctx, p)
	case "smoke.report":
		return b.smokeReport(p)
	case "smoke.last_result":
		return b.smokeLast(p), nil
	case "release.readiness":
		return s.ReleaseReadiness().Status(), nil
	case "final.preflight":
		return b.finalPreflight()
	case "final.packaging_audit":
		return b.finalPackaging()
	case "final.no_webui_regression":
		return b.finalNoWebUI()
	case "final.release_seal":
		return b.finalSeal()
	}
	return nil, protocolError("UNSUPPORTED_OPERATION", "Unsupported operation: "+op, nil)
}

func copyMap(p map[string]any) map[string]any {
	q := map[string]any{}
	for k, v := range p {
		q[k] = v
	}
	return q
}
func (b *ServicesBackend) catalogList(ctx context.Context, p map[string]any) (any, error) {
	kind, e := catalogKind(p)
	if e != nil {
		return nil, e
	}
	target := optText(p, "name")
	if target == "" {
		target = optText(p, "targetName")
	}
	distro := optText(p, "distro")
	category := optText(p, "category")
	query := strings.ToLower(optText(p, "query"))
	if query == "" {
		query = strings.ToLower(optText(p, "q"))
	}
	svc := b.Services.Catalog(kind, target)
	entries, e := svc.ListEntries(distro, category)
	if e != nil {
		return nil, e
	}
	out := []map[string]any{}
	for _, entry := range entries {
		if query != "" {
			hay := strings.ToLower(entry.Name + " " + entry.Description + " " + strings.Join(entry.Categories, " ") + " " + strings.Join(entry.Distros, " "))
			if !strings.Contains(hay, query) {
				continue
			}
		}
		out = append(out, entryPayload(entry))
	}
	cats, e := svc.Categories(distro)
	if e != nil {
		return nil, e
	}
	return map[string]any{"kind": kind, "targetName": emptyNil(target), "entries": out, "categories": cats, "distros": b.Services.Install().Distros(), "query": query, "category": emptyNil(category), "distro": emptyNil(distro)}, nil
}
func emptyNil(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func (b *ServicesBackend) preview(ctx context.Context, op string, p map[string]any) (any, error) {
	s := b.Services
	switch op {
	case "install.preview":
		return s.Preview().Install(ctx, installRequest(p))
	case "chroots.remove":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		return s.Chroots().DeletePreview(ctx, n)
	case "chroots.export":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		return s.Chroots().ExportPreview(ctx, n, optText(p, "archive"))
	case "chroots.lifecycle.preview":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		a := optText(p, "action")
		if a == "" {
			a = "start"
		}
		switch a {
		case "remove":
			return s.Chroots().DeletePreview(ctx, n)
		case "upgrade":
			return s.Preview().Upgrade(ctx, n)
		case "start", "restart":
			d, e := s.Chroots().Get(ctx, n)
			if e != nil {
				return nil, e
			}
			blocking := []map[string]string{}
			if d.Path == "" {
				blocking = append(blocking, map[string]string{"code": "missing_path", "message": "No chroot path is registered."})
			}
			warnings := []string{}
			if !d.Installed {
				warnings = append(warnings, "Chroot is not marked fully installed yet.")
			}
			return map[string]any{"ok": len(blocking) == 0, "kind": a, "name": n, "path": d.Path, "installed": d.Installed, "warnings": warnings, "blocking": blocking, "confirm": a == "restart", "dry_run": map[string]any{"supported": true, "command": "chrootctl --name " + n + " " + a + " --dry-run"}}, nil
		default:
			return nil, protocolError("INVALID_LIFECYCLE_ACTION", "Unsupported lifecycle action: "+a, nil)
		}
	case "snapshots.preview":
		return b.snapshotPreview(ctx, p)
	case "users.preview":
		return b.userPreview(ctx, p)
	case "services.preview":
		return b.servicePreview(ctx, p)
	case "catalog.preview":
		return b.catalogPreview(ctx, p)
	case "transfer.import_preview":
		a := optText(p, "archive")
		if a == "" {
			a = optText(p, "path")
		}
		return s.Preview().Import(ctx, a, optText(p, "name"), optText(p, "conflict"), optText(p, "password"))
	case "transfer.preview_export":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		return s.Preview().Export(ctx, n, optText(p, "archive"))
	case "artifacts.cleanup_preview":
		return b.cleanupPreview(ctx, p, false)
	case "support.preview":
		archive := optText(p, "archive")
		if archive == "" {
			archive = filepath.Join(services.ManagedTransferRoot(), "chrootctl-support.tar.gz")
		}
		return map[string]any{"ok": true, "kind": "support.bundle", "archive": archive, "warnings": []string{"Support bundles are sanitized before export."}, "blocking": []any{}, "confirm": false}, nil
	case "system.module_build_preview":
		return b.moduleBuildPreview(p)
	case "repair.preview":
		ds, e := decisions(p)
		if e != nil {
			return nil, e
		}
		if len(ds) == 0 {
			items, e := s.Repair().PreviewItems(ctx)
			return map[string]any{"ok": e == nil, "items": items, "decisions": []any{}}, e
		}
		return s.Repair().PreviewPlan(ctx, ds)
	case "cleanup.temp_preview":
		return b.cleanupPreview(ctx, p, true)
	case "smoke.preview":
		return b.smokePlan(ctx, p)
	}
	return nil, protocolError("UNSUPPORTED_OPERATION", "Unsupported operation: "+op, nil)
}

func (b *ServicesBackend) snapshotPreview(ctx context.Context, p map[string]any) (any, error) {
	n, e := reqName(p)
	if e != nil {
		return nil, e
	}
	a := optText(p, "action")
	if a == "" {
		a = "create"
	}
	rows, e := b.Services.Snapshots().List(ctx, n, 100)
	if e != nil {
		return nil, e
	}
	snap := optText(p, "snapshot")
	if snap == "" {
		snap = optText(p, "snapshotName")
	}
	if snap == "" {
		snap = optText(p, "snapshot_name")
	}
	switch a {
	case "create":
		if snap == "" {
			snap = "snapshot"
		}
		snap, e = validation.SnapshotNameField(snap, "payload.snapshot")
		if e != nil {
			return nil, e
		}
		exists := false
		for _, r := range rows {
			if r.Name == snap {
				exists = true
			}
		}
		block := []map[string]string{}
		if exists {
			block = append(block, map[string]string{"code": "snapshot_exists", "message": "Snapshot already exists: " + snap})
		}
		return map[string]any{"ok": len(block) == 0, "kind": "snapshot.create", "name": n, "snapshot": snap, "existingCount": len(rows), "blocking": block, "warnings": []string{}, "confirm": false}, nil
	case "restore":
		snap, e = reqSnapshot(p)
		if e != nil {
			return nil, e
		}
		exists := false
		for _, r := range rows {
			if r.Name == snap {
				exists = true
			}
		}
		block := []map[string]string{}
		if !exists {
			block = append(block, map[string]string{"code": "snapshot_missing", "message": "Snapshot does not exist: " + snap})
		}
		return map[string]any{"ok": len(block) == 0, "kind": "snapshot.restore", "name": n, "snapshot": snap, "destructive": true, "blocking": block, "warnings": []string{"Restore replaces the current chroot files with the selected snapshot."}, "confirm": true}, nil
	case "export":
		snap, e = reqSnapshot(p)
		if e != nil {
			return nil, e
		}
		archive := optText(p, "archive")
		if archive == "" {
			archive = "./" + n + "-" + snap + ".tar.gz"
		}
		return map[string]any{"ok": true, "kind": "snapshot.export", "name": n, "snapshot": snap, "archive": archive, "blocking": []any{}, "warnings": []any{}, "confirm": false}, nil
	default:
		return nil, protocolError("INVALID_SNAPSHOT_ACTION", "Unsupported snapshot action: "+a, nil)
	}
}
func (b *ServicesBackend) userPreview(ctx context.Context, p map[string]any) (any, error) {
	n, e := reqName(p)
	if e != nil {
		return nil, e
	}
	u, e := reqUser(p)
	if e != nil {
		return nil, e
	}
	a := strings.ReplaceAll(optText(p, "action"), "-", "_")
	if a == "" {
		a = "add"
	}
	existing, _ := b.Services.Users(n).List(ctx)
	present := false
	for _, r := range existing {
		if asString(r["username"]) == u {
			present = true
		}
	}
	blocking := []map[string]string{}
	warnings := []string{}
	switch a {
	case "add":
		if present {
			blocking = append(blocking, map[string]string{"code": "user_exists", "message": "User already exists: " + u})
		}
	case "remove", "sync_uid_gid", "set_shell", "set_sudo", "set_password", "password":
		if !present {
			blocking = append(blocking, map[string]string{"code": "user_missing", "message": "User does not exist: " + u})
		}
	default:
		return nil, protocolError("INVALID_USER_ACTION", "Unsupported user action: "+a, nil)
	}
	return map[string]any{"ok": len(blocking) == 0, "kind": "users." + a, "name": n, "username": u, "blocking": blocking, "warnings": warnings, "confirm": a == "remove" || a == "set_password" || a == "password"}, nil
}
func (b *ServicesBackend) servicePreview(ctx context.Context, p map[string]any) (any, error) {
	unit, e := reqService(p)
	if e != nil {
		return nil, e
	}
	name := optText(p, "name")
	if name == "" {
		name = optText(p, "chroot")
	}
	a := optText(p, "action")
	if a == "" {
		a = "start"
	}
	if a != "start" && a != "stop" && a != "restart" && a != "enable" && a != "disable" {
		return nil, protocolError("INVALID_SERVICE_ACTION", "Unsupported service action: "+a, nil)
	}
	st, e := b.Services.Services().Status(ctx, unit, name)
	if e != nil {
		return nil, e
	}
	warnings := []string{}
	status := asString(st["status"])
	if (a == "stop" || a == "restart") && status != "running" && status != "stale" {
		warnings = append(warnings, "Service is not currently running.")
	}
	return map[string]any{"ok": true, "kind": "services." + a, "name": name, "service": unit, "status": st, "blocking": []any{}, "warnings": warnings, "confirm": a == "restart" || a == "disable"}, nil
}
func (b *ServicesBackend) catalogPreview(ctx context.Context, p map[string]any) (any, error) {
	kind, e := catalogKind(p)
	if e != nil {
		return nil, e
	}
	n, e := reqName(p)
	if e != nil {
		return nil, e
	}
	names, e := catalogNames(p)
	if e != nil {
		return nil, e
	}
	if len(names) == 0 {
		return map[string]any{"ok": false, "kind": "catalog.apply", "name": n, "catalogKind": kind, "blocking": []map[string]string{{"code": "missing_entries", "message": "Choose at least one catalog entry."}}, "warnings": []string{}, "entries": []any{}}, nil
	}
	detail, e := b.Services.Chroots().Get(ctx, n)
	if e != nil {
		return nil, e
	}
	svc := b.Services.Catalog(kind, n)
	block := []map[string]string{}
	entries := []map[string]any{}
	for _, name := range names {
		entry, e := svc.GetEntry(name)
		if e != nil {
			block = append(block, map[string]string{"code": "unknown_entry", "message": "Unknown " + kind + ": " + name})
			continue
		}
		entries = append(entries, entryPayload(entry))
		if detail.Distro != "" && !entry.MatchesDistro(detail.Distro) {
			block = append(block, map[string]string{"code": "unsupported_distro", "message": entry.Name + " does not support " + detail.Distro + "."})
		}
		missing, e := svc.Preflight(ctx, entry)
		if e == nil && len(missing) > 0 {
			block = append(block, map[string]string{"code": "missing_commands", "message": entry.Name + " requires: " + strings.Join(missing, ", ")})
		}
	}
	return map[string]any{"ok": len(block) == 0, "kind": "catalog.apply", "name": n, "catalogKind": kind, "entries": entries, "blocking": block, "warnings": []string{}, "confirm": false}, nil
}
func (b *ServicesBackend) cleanupPreview(ctx context.Context, p map[string]any, temp bool) (any, error) {
	id := optText(p, "artifactId")
	if id == "" {
		id = optText(p, "artifact_id")
	}
	path := optText(p, "path")
	all, _ := optBool(p, []string{"deleteAll", "delete_all"}, false)
	if temp {
		state, e := b.Services.Transfer().TempState(ctx)
		if e != nil {
			return nil, e
		}
		return map[string]any{"ok": true, "kind": "cleanup.temp", "artifactId": id, "path": path, "deleteAll": all, "state": state, "confirm": true}, nil
	}
	arts, e := b.Services.Registry.ListArtifacts(ctx, true, 500)
	if e != nil {
		return nil, e
	}
	return map[string]any{"ok": true, "kind": "artifacts.cleanup", "artifactId": id, "path": path, "deleteAll": all, "artifacts": arts, "confirm": true}, nil
}
func (b *ServicesBackend) moduleBuildPreview(p map[string]any) (any, error) {
	targets := asStringSlice(p["startupTargets"])
	all, _ := optBool(p, []string{"allInstalled", "all_installed"}, false)
	archive := optText(p, "archive")
	if archive == "" {
		archive = "./chrootctl-magisk.zip"
	}
	return map[string]any{"ok": true, "kind": "system.module_build", "archive": archive, "startupTargets": targets, "allInstalled": all, "blocking": []any{}, "warnings": []string{"GO12 will replace the legacy module builder with the native Go packager."}, "confirm": false}, nil
}

func (b *ServicesBackend) operation(ctx context.Context, op string, p map[string]any, progress Progress, isCancelled func() bool) (any, error) {
	s := b.Services
	switch op {
	case "operations.retry":
		return b.retry(ctx, p, progress, isCancelled)
	case "system.refresh":
		if e := emit(progress, map[string]any{"phase": "registry", "percent": 35, "message": "Reading chroot registry"}); e != nil {
			return nil, e
		}
		rows, e := s.Chroots().List(ctx)
		if e != nil {
			return nil, e
		}
		if e = cancelled(isCancelled, "Refresh was cancelled"); e != nil {
			return nil, e
		}
		d, e := s.System().Dashboard(ctx, "", true, 20)
		if e != nil {
			return nil, e
		}
		_ = emit(progress, map[string]any{"phase": "complete", "percent": 100, "message": "State refresh completed"})
		return map[string]any{"dashboard": d, "chroots": rows}, nil
	case "install.run":
		r := installRequest(p)
		prev, e := s.Preview().Install(ctx, r)
		if e != nil {
			return nil, e
		}
		if ok, v := prev["ok"].(bool); ok && !v {
			return nil, protocolError("INSTALL_PREVIEW_BLOCKED", "Install preview reported blocking issues", nil)
		}
		if e = cancelled(isCancelled, "Install was cancelled before execution"); e != nil {
			return nil, e
		}
		return s.Install().Install(ctx, r, func(v any) error {
			if e := emit(progress, v); e != nil {
				return e
			}
			return cancelled(isCancelled, "Install was cancelled")
		})
	case "chroots.start", "chroots.restart":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		if e = cancelled(isCancelled, "Lifecycle action was cancelled"); e != nil {
			return nil, e
		}
		_ = emit(progress, map[string]any{"phase": "start", "percent": 10, "message": op + " " + n})
		if op == "chroots.start" {
			return s.Chroots().Start(ctx, n)
		}
		return s.Chroots().Restart(ctx, n)
	case "chroots.upgrade":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		prev, e := s.Preview().Upgrade(ctx, n)
		if e != nil {
			return nil, e
		}
		if ok, _ := prev["ok"].(bool); !ok {
			return nil, protocolError("UPGRADE_PREVIEW_BLOCKED", "Upgrade preview reported blocking issues", nil)
		}
		return s.Install().Upgrade(ctx, n, optText(p, "username"), func(v any) error {
			if e := emit(progress, v); e != nil {
				return e
			}
			return cancelled(isCancelled, "Upgrade was cancelled")
		})
	case "chroots.remove.execute":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		confirmation := optText(p, "confirmation")
		if confirmation == "" {
			confirmation = optText(p, "confirmName")
		}
		if confirmation != n {
			return nil, protocolError("CONFIRMATION_REQUIRED", "payload.confirmation must match payload.name", nil)
		}
		return s.Chroots().Remove(ctx, n)
	case "snapshots.create":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		snap := optText(p, "snapshot")
		if snap == "" {
			snap = optText(p, "snapshotName")
		}
		if snap == "" {
			snap = "snapshot"
		}
		return s.Snapshots().Create(ctx, n, snap, optText(p, "description"))
	case "snapshots.restore":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		snap, e := reqSnapshot(p)
		if e != nil {
			return nil, e
		}
		if optText(p, "confirmation") != n {
			return nil, protocolError("CONFIRMATION_REQUIRED", "payload.confirmation must match payload.name", nil)
		}
		return s.Snapshots().Restore(ctx, n, snap)
	case "snapshots.export":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		snap, e := reqSnapshot(p)
		if e != nil {
			return nil, e
		}
		return s.Snapshots().Export(ctx, n, snap, optText(p, "archive"))
	case "users.add":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		u, e := reqUser(p)
		if e != nil {
			return nil, e
		}
		sudo, _ := optBool(p, []string{"sudo"}, false)
		return s.Users(n).Add(ctx, u, optText(p, "shell"), sudo)
	case "users.remove":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		u, e := reqUser(p)
		if e != nil {
			return nil, e
		}
		confirm := optText(p, "confirmation")
		if confirm == "" {
			confirm = optText(p, "confirmUsername")
		}
		if confirm != u {
			return nil, protocolError("CONFIRMATION_REQUIRED", "payload.confirmation must match payload.username", nil)
		}
		del, _ := optBool(p, []string{"deleteHome"}, false)
		return s.Users(n).Remove(ctx, u, del)
	case "users.sync_uid_gid":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		u, e := reqUser(p)
		if e != nil {
			return nil, e
		}
		fix, _ := optBool(p, []string{"fixOwnership"}, false)
		return s.Users(n).SyncID(ctx, u, fix)
	case "users.set_shell":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		u, e := reqUser(p)
		if e != nil {
			return nil, e
		}
		shell := optText(p, "shell")
		if shell == "" {
			return nil, protocolError("MISSING_SHELL", "payload.shell is required", nil)
		}
		return s.Users(n).SetShell(ctx, u, shell)
	case "users.set_sudo":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		u, e := reqUser(p)
		if e != nil {
			return nil, e
		}
		enabled, e := optBool(p, []string{"enabled", "sudo"}, true)
		if e != nil {
			return nil, e
		}
		return s.Users(n).SetSudo(ctx, u, enabled)
	case "users.set_password":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		u, e := reqUser(p)
		if e != nil {
			return nil, e
		}
		confirm := optText(p, "confirmation")
		if confirm == "" {
			confirm = optText(p, "confirmUsername")
		}
		if confirm != u {
			return nil, protocolError("CONFIRMATION_REQUIRED", "payload.confirmation must match payload.username", nil)
		}
		password := asString(p["password"])
		if password == "" {
			return nil, protocolError("MISSING_PASSWORD", "payload.password is required", nil)
		}
		if v, ok := p["confirmPassword"]; ok && asString(v) != password {
			return nil, protocolError("PASSWORD_CONFIRMATION_MISMATCH", "payload.confirmPassword does not match payload.password", nil)
		}
		return s.Users(n).SetPassword(ctx, u, password)
	case "services.start", "services.stop", "services.restart", "services.enable", "services.disable":
		unit, e := reqService(p)
		if e != nil {
			return nil, e
		}
		name := optText(p, "name")
		if name == "" {
			name = optText(p, "chroot")
		}
		switch strings.TrimPrefix(op, "services.") {
		case "start":
			return s.Services().Start(ctx, unit, name, false)
		case "stop":
			return s.Services().Stop(ctx, unit, name)
		case "restart":
			return s.Services().Restart(ctx, unit, name)
		case "enable":
			return s.Services().Enable(ctx, unit, name, defaultText(optText(p, "target"), "boot.target"))
		default:
			return s.Services().Disable(ctx, unit, name, defaultText(optText(p, "target"), "boot.target"))
		}
	case "catalog.apply":
		kind, e := catalogKind(p)
		if e != nil {
			return nil, e
		}
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		names, e := catalogNames(p)
		if e != nil {
			return nil, e
		}
		return s.Catalog(kind, n).Apply(ctx, names, func(v any) error {
			if e := emit(progress, v); e != nil {
				return e
			}
			return cancelled(isCancelled, "Catalog apply was cancelled")
		})
	case "transfer.import":
		a := optText(p, "archive")
		if a == "" {
			a = optText(p, "path")
		}
		if a == "" {
			return nil, protocolError("MISSING_ARCHIVE", "payload.archive is required", nil)
		}
		post := optText(p, "postImport")
		if post == "" {
			post = optText(p, "post_import")
		}
		return s.Transfer().Import(ctx, a, optText(p, "name"), defaultText(optText(p, "conflict"), "fail"), optText(p, "password"), post)
	case "transfer.export":
		n, e := reqName(p)
		if e != nil {
			return nil, e
		}
		return s.Transfer().Export(ctx, n, optText(p, "archive"), optText(p, "password"))
	case "artifacts.cleanup":
		return b.cleanup(ctx, p, false)
	case "support.bundle":
		return s.Support().ExportBundle(ctx, optText(p, "archive"), map[string]any{})
	case "system.module_build":
		return b.moduleBuild(ctx, p, progress, isCancelled)
	case "repair.apply":
		ds, e := decisions(p)
		if e != nil {
			return nil, e
		}
		if len(ds) == 0 {
			return nil, protocolError("REPAIR_DECISIONS_REQUIRED", "payload.decisions is required", nil)
		}
		return s.Repair().ApplyPlan(ctx, ds)
	case "cleanup.temp":
		return b.cleanup(ctx, p, true)
	case "debug.export":
		return b.debugExport(ctx, p)
	case "smoke.run":
		return b.smokeRun(ctx, p, progress, isCancelled)
	case "smoke.result.persist":
		return b.smokeArtifact(ctx, p, "persist")
	case "smoke.result.export":
		return b.smokeArtifact(ctx, p, "export")
	case "smoke.failure.bundle":
		last := b.smokeLast(p)
		return s.Support().ExportBundle(ctx, optText(p, "archive"), map[string]any{"smoke": last})
	}
	return nil, protocolError("UNSUPPORTED_OPERATION", "Unsupported operation: "+op, nil)
}
func defaultText(v, d string) string {
	if strings.TrimSpace(v) == "" {
		return d
	}
	return v
}

func (b *ServicesBackend) retry(ctx context.Context, p map[string]any, progress Progress, cancel func() bool) (any, error) {
	id := optText(p, "operationId")
	if id == "" {
		id = optText(p, "operation_id")
	}
	if id == "" {
		id = optText(p, "id")
	}
	if id == "" {
		return nil, protocolError("MISSING_OPERATION_ID", "payload.operationId is required", nil)
	}
	mode := defaultText(optText(p, "mode"), "retry")
	if mode != "retry" && mode != "repair" {
		return nil, protocolError("INVALID_RETRY_MODE", "Unsupported retry mode: "+mode, nil)
	}
	r, e := b.Services.Operations.Get(id, 200)
	if e != nil {
		return nil, e
	}
	stored := r.Retry
	if len(stored) == 0 {
		stored = r.Request
	}
	if len(stored) == 0 {
		return nil, protocolError("RETRY_REQUEST_UNAVAILABLE", "The operation journal does not contain a retry request", nil)
	}
	if containsRedacted(stored) {
		return nil, protocolError("REDACTED_RETRY_REQUEST", "The stored retry request contains redacted secrets; re-enter the sensitive fields instead of replaying it.", nil)
	}
	op := optText(stored, "operation")
	payload, _ := stored["payload"].(map[string]any)
	if op == "" || op == "operations.retry" {
		return nil, protocolError("INVALID_RETRY_OPERATION", "The stored request cannot be replayed", nil)
	}
	spec, ok := Specs[op]
	if !ok || spec.Mode != "operation" {
		return nil, protocolError("UNSUPPORTED_RETRY_OPERATION", "Cannot retry unsupported operation: "+op, nil)
	}
	if previewRequired[op] {
		return nil, protocolError("PREVIEW_RETRY_REQUIRES_PREVIEW", "Preview-bound operations must be previewed again before retrying so stale approvals cannot be replayed.", nil)
	}
	if mode == "repair" {
		if op != "install.run" {
			return nil, protocolError("RETRY_FIXES_UNSUPPORTED", "Retry with fixes is available only for install operations", nil)
		}
		payload["repair"] = true
		payload["resume"] = true
	}
	_ = emit(progress, map[string]any{"phase": "retry", "percent": 5, "message": "Preparing retry for " + op})
	result, e := b.operation(ctx, op, payload, progress, cancel)
	if e != nil {
		return nil, e
	}
	return map[string]any{"retriedOperationId": id, "operation": op, "mode": mode, "result": result, "next_steps": []string{"Review the new operation record in Activity."}}, nil
}
func containsRedacted(v any) bool {
	switch x := v.(type) {
	case map[string]any:
		for _, i := range x {
			if containsRedacted(i) {
				return true
			}
		}
	case []any:
		for _, i := range x {
			if containsRedacted(i) {
				return true
			}
		}
	case string:
		s := strings.ToLower(strings.TrimSpace(x))
		return s == "<redacted>" || s == "[redacted]" || s == "redacted" || strings.Contains(s, "<redacted>") || strings.Contains(s, "[redacted]")
	}
	return false
}

func (b *ServicesBackend) cleanup(ctx context.Context, p map[string]any, temp bool) (any, error) {
	id := optText(p, "artifactId")
	if id == "" {
		id = optText(p, "artifact_id")
	}
	path := optText(p, "path")
	all, _ := optBool(p, []string{"deleteAll", "delete_all"}, false)
	if temp {
		return b.Services.Transfer().DeleteTemp(ctx, id, path, all)
	}
	arts, e := b.Services.Registry.ListArtifacts(ctx, true, 500)
	if e != nil {
		return nil, e
	}
	deleted := []string{}
	for _, a := range arts {
		match := all || (id != "" && a.ArtifactID == id) || (path != "" && a.Path == path)
		if !match {
			continue
		}
		if !b.Services.DryRun {
			_ = os.Remove(a.Path)
			if e = b.Services.Registry.DeleteArtifact(ctx, a.ArtifactID); e != nil {
				return nil, e
			}
		}
		deleted = append(deleted, a.ArtifactID)
	}
	return map[string]any{"deleted": deleted, "count": len(deleted), "dry_run": b.Services.DryRun}, nil
}
func (b *ServicesBackend) moduleBuild(ctx context.Context, p map[string]any, progress Progress, cancel func() bool) (any, error) {
	prev, _ := b.moduleBuildPreview(p)
	_ = emit(progress, map[string]any{"phase": "module", "percent": 10, "message": "Building module artifact"})
	if e := cancelled(cancel, "Module build was cancelled"); e != nil {
		return nil, e
	}
	if b.Services.DryRun {
		return map[string]any{"dry_run": true, "preview": prev}, nil
	}
	if _, e := os.Stat("build.sh"); e != nil {
		return nil, protocolError("MODULE_BUILDER_UNAVAILABLE", "Legacy module builder is unavailable; GO12 native packaging has not been applied yet", nil)
	}
	cmd := exec.CommandContext(ctx, "bash", "build.sh")
	out, e := cmd.CombinedOutput()
	if e != nil {
		return nil, fmt.Errorf("module build failed: %s", strings.TrimSpace(string(out)))
	}
	_ = emit(progress, map[string]any{"phase": "complete", "percent": 100, "message": "Module build completed"})
	return map[string]any{"built": true, "output": strings.TrimSpace(string(out)), "preview": prev}, nil
}
func (b *ServicesBackend) debugProbes(ctx context.Context, group string) (any, error) {
	if group == "" {
		group = "all"
	}
	rows := []map[string]any{{"group": "runtime", "name": "lifecycle", "result": b.Services.Lifecycle().Status()}, {"group": "runtime", "name": "module", "result": b.Services.ModuleRuntime().Status()}, {"group": "host", "name": "doctor", "result": b.Services.Doctor().HostReadiness(ctx)}}
	return map[string]any{"group": group, "probes": rows}, nil
}
func (b *ServicesBackend) debugExport(ctx context.Context, p map[string]any) (any, error) {
	probes, e := b.debugProbes(ctx, optText(p, "group"))
	if e != nil {
		return nil, e
	}
	events, _ := b.Services.Audit().Recent(ctx, 100)
	return b.Services.Support().ExportBundle(ctx, optText(p, "archive"), map[string]any{"debug": probes, "timeline": events})
}
func smokeSteps(target string) []map[string]any {
	return []map[string]any{{"id": "runtime", "label": "Runtime readiness", "required": true}, {"id": "module", "label": "Module status", "required": true}, {"id": "registry", "label": "Registry read", "required": true}, {"id": "dashboard", "label": "Dashboard state", "required": true}, {"id": "target", "label": "Target status", "required": target != ""}}
}
func (b *ServicesBackend) smokePlan(ctx context.Context, p map[string]any) (any, error) {
	target := optText(p, "name")
	if target == "" {
		target = optText(p, "target")
	}
	optional, _ := optBool(p, []string{"includeOptional", "include_optional"}, false)
	return map[string]any{"ok": true, "target": emptyNil(target), "scope": defaultText(optText(p, "scope"), "read-only"), "includeOptional": optional, "steps": smokeSteps(target), "destructive": false}, nil
}
func (b *ServicesBackend) smokeRun(ctx context.Context, p map[string]any, progress Progress, cancel func() bool) (any, error) {
	plan, _ := b.smokePlan(ctx, p)
	target := optText(p, "name")
	if target == "" {
		target = optText(p, "target")
	}
	results := []map[string]any{}
	steps := smokeSteps(target)
	for i, step := range steps {
		if e := cancelled(cancel, "Smoke run was cancelled"); e != nil {
			return nil, e
		}
		_ = emit(progress, map[string]any{"phase": "smoke", "percent": 5 + (i * 90 / max(1, len(steps))), "message": "Running " + asString(step["label"])})
		id := asString(step["id"])
		var val any
		var e error
		switch id {
		case "runtime":
			val = b.Services.Lifecycle().Status()
		case "module":
			val = b.Services.ModuleRuntime().Status()
		case "registry":
			val, e = b.Services.Chroots().List(ctx)
		case "dashboard":
			val, e = b.Services.System().Dashboard(ctx, target, true, 20)
		case "target":
			val, e = b.Services.System().Status(ctx, target, true)
		}
		results = append(results, map[string]any{"id": id, "ok": e == nil, "result": val, "error": errText(e)})
	}
	failed := 0
	for _, r := range results {
		if ok, _ := r["ok"].(bool); !ok {
			failed++
		}
	}
	return map[string]any{"ok": failed == 0, "plan": plan, "results": results, "failed": failed, "completedAt": float64(time.Now().UnixNano()) / 1e9}, nil
}
func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
func errText(e error) any {
	if e == nil {
		return nil
	}
	return e.Error()
}
func (b *ServicesBackend) smokeReport(p map[string]any) (any, error) {
	lim := 25
	if v, e := bounded(p, "limit", 25, 1, 200, "INVALID_SMOKE_LIMIT"); e == nil {
		lim = v
	}
	rows, e := b.Services.Operations.ListRecent(lim, nil)
	if e != nil {
		return nil, e
	}
	out := []operations.Record{}
	for _, r := range rows {
		if r.Kind == "smoke.run" {
			out = append(out, r)
		}
	}
	return map[string]any{"operations": out, "count": len(out)}, nil
}
func (b *ServicesBackend) smokeLast(p map[string]any) any {
	report, e := b.smokeReport(p)
	if e != nil {
		return map[string]any{"ok": false, "error": e.Error()}
	}
	rows, _ := report.(map[string]any)["operations"].([]operations.Record)
	if len(rows) == 0 {
		return map[string]any{"ok": false, "status": "missing", "nextSteps": []string{"Run the smoke suite before requesting the latest result."}}
	}
	return map[string]any{"ok": rows[0].State == "succeeded", "status": rows[0].State, "operation": rows[0]}
}
func (b *ServicesBackend) smokeArtifact(ctx context.Context, p map[string]any, kind string) (any, error) {
	last := b.smokeLast(p)
	archive := optText(p, "archive")
	if archive == "" {
		archive = filepath.Join(services.ManagedTransferRoot(), "smoke-result-"+kind+".json")
	}
	if !b.Services.DryRun {
		if e := os.MkdirAll(filepath.Dir(archive), 0o755); e != nil {
			return nil, e
		}
		data, _ := json.MarshalIndent(last, "", "  ")
		if e := os.WriteFile(archive, append(data, '\n'), 0o600); e != nil {
			return nil, e
		}
	}
	a, e := b.Services.Transfer().RegisterArtifact(ctx, archive, "smoke-result", "", nil, map[string]any{"kind": kind})
	return map[string]any{"archive": archive, "artifact": a, "result": last}, e
}
func (b *ServicesBackend) finalPreflight() (any, error) {
	s := b.Services.ReleaseReadiness().Status()
	return map[string]any{"ok": s["ready"], "readiness": s, "runtime": b.Services.Lifecycle().Status(), "module": b.Services.ModuleRuntime().Status()}, nil
}
func (b *ServicesBackend) finalPackaging() (any, error) {
	m := b.Services.ModuleRuntime().Status()
	return map[string]any{"ok": m["status"] == "ready", "module": m, "compatibilitySchemaVersion": 3, "bridgeProtocolVersion": 1}, nil
}
func (b *ServicesBackend) finalNoWebUI() (any, error) {
	return map[string]any{"ok": true, "retired": true, "checks": []string{"No WebUI runtime is required by the Go backend.", "Android communicates only through protocol-v1 bridge operations."}}, nil
}
func (b *ServicesBackend) finalSeal() (any, error) {
	pre, _ := b.finalPreflight()
	pack, _ := b.finalPackaging()
	web, _ := b.finalNoWebUI()
	ok, _ := pre.(map[string]any)["ok"].(bool)
	pok, _ := pack.(map[string]any)["ok"].(bool)
	wok, _ := web.(map[string]any)["ok"].(bool)
	return map[string]any{"ok": ok && pok && wok, "preflight": pre, "packaging": pack, "noWebui": web}, nil
}
