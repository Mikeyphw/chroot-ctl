package bridge

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"chrootctl/internal/redaction"
)

const PreviewSchemaVersion = 1
const PreviewTTL = 15 * time.Minute

var previewRequired = map[string]bool{
	"install.run": true, "chroots.start": true, "chroots.restart": true, "chroots.upgrade": true, "chroots.remove.execute": true,
	"snapshots.create": true, "snapshots.restore": true, "snapshots.export": true, "users.add": true, "users.remove": true, "users.sync_uid_gid": true,
	"users.set_shell": true, "users.set_sudo": true, "users.set_password": true, "services.start": true, "services.stop": true, "services.restart": true,
	"services.enable": true, "services.disable": true, "smoke.run": true, "catalog.apply": true, "transfer.import": true, "transfer.export": true,
	"artifacts.cleanup": true, "support.bundle": true, "system.module_build": true, "repair.apply": true, "cleanup.temp": true,
}
var unboundFields = map[string]bool{"action": true, "confirmation": true, "confirmName": true, "confirmUsername": true, "password": true, "confirmPassword": true, "title": true, "previewId": true, "payloadHash": true, "resourceRevision": true}

type PreviewStore struct {
	Root string
	Now  func() time.Time
}

func NewPreviewStore(root string) (*PreviewStore, error) {
	if err := os.MkdirAll(root, 0o755); err != nil {
		return nil, err
	}
	return &PreviewStore{Root: root, Now: time.Now}, nil
}
func randomHex(n int) string {
	b := make([]byte, n)
	if _, e := rand.Read(b); e != nil {
		return fmt.Sprintf("%032x", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}
func canonical(v any) []byte { b, _ := json.Marshal(v); return b }
func bindingHash(action string, payload map[string]any) string {
	clean := map[string]any{}
	keys := make([]string, 0, len(payload))
	for k := range payload {
		if !unboundFields[k] {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	for _, k := range keys {
		clean[k] = payload[k]
	}
	sum := sha256.Sum256(canonical(map[string]any{"actionOperation": action, "payload": clean}))
	return hex.EncodeToString(sum[:])
}
func resourceRevision(result any) string {
	var normalized any = result
	b, _ := json.Marshal(result)
	_ = json.Unmarshal(b, &normalized)
	if m, ok := normalized.(map[string]any); ok {
		delete(m, "previewId")
		delete(m, "payloadHash")
		delete(m, "resourceRevision")
		delete(m, "expiresAt")
		delete(m, "actionOperation")
	}
	sum := sha256.Sum256(canonical(normalized))
	return hex.EncodeToString(sum[:])
}
func atomicJSON(path string, v any) error {
	dir := filepath.Dir(path)
	tmp, e := os.CreateTemp(dir, "."+filepath.Base(path)+".*")
	if e != nil {
		return e
	}
	name := tmp.Name()
	defer os.Remove(name)
	enc := json.NewEncoder(tmp)
	enc.SetEscapeHTML(false)
	if e = enc.Encode(v); e == nil {
		e = tmp.Sync()
	}
	if ce := tmp.Close(); e == nil {
		e = ce
	}
	if e != nil {
		return e
	}
	return os.Rename(name, path)
}
func (s *PreviewStore) Issue(previewOp, actionOp string, payload map[string]any, result any) (map[string]any, error) {
	id := randomHex(16)
	now := s.Now()
	rec := map[string]any{"schemaVersion": PreviewSchemaVersion, "previewId": id, "previewOperation": previewOp, "actionOperation": actionOp, "payloadHash": bindingHash(actionOp, payload), "resourceRevision": resourceRevision(result), "previewPayload": redaction.Value(payload), "createdAt": float64(now.UnixNano()) / 1e9, "expiresAt": float64(now.Add(PreviewTTL).UnixNano()) / 1e9}
	if e := atomicJSON(filepath.Join(s.Root, id+".json"), rec); e != nil {
		return nil, e
	}
	return map[string]any{"previewId": id, "actionOperation": actionOp, "payloadHash": rec["payloadHash"], "resourceRevision": rec["resourceRevision"], "expiresAt": rec["expiresAt"]}, nil
}
func validPreviewID(id string) bool {
	if len(id) != 32 {
		return false
	}
	for _, c := range id {
		if !strings.ContainsRune("0123456789abcdef", c) {
			return false
		}
	}
	return true
}
func (s *PreviewStore) Verify(action string, payload map[string]any) (map[string]any, error) {
	id := strings.TrimSpace(asString(payload["previewId"]))
	ph := strings.TrimSpace(asString(payload["payloadHash"]))
	rr := strings.TrimSpace(asString(payload["resourceRevision"]))
	if id == "" || ph == "" || rr == "" {
		return nil, protocolError("PREVIEW_CONTRACT_REQUIRED", action+" requires previewId, payloadHash, and resourceRevision from a fresh preview", nil)
	}
	if !validPreviewID(id) {
		return nil, protocolError("INVALID_PREVIEW_ID", "payload.previewId is invalid", nil)
	}
	src := filepath.Join(s.Root, id+".json")
	claim := filepath.Join(s.Root, "."+id+"."+randomHex(8)+".claim")
	if e := os.Rename(src, claim); e != nil {
		if os.IsNotExist(e) {
			return nil, protocolError("PREVIEW_NOT_FOUND", "Preview approval is missing or has already been consumed", nil)
		}
		return nil, protocolError("PREVIEW_CLAIM_FAILED", "Preview approval could not be claimed safely", nil)
	}
	defer os.Remove(claim)
	b, e := os.ReadFile(claim)
	if e != nil {
		return nil, protocolError("PREVIEW_RECORD_INVALID", "Preview approval record is invalid", nil)
	}
	var rec map[string]any
	if json.Unmarshal(b, &rec) != nil {
		return nil, protocolError("PREVIEW_RECORD_INVALID", "Preview approval record is invalid", nil)
	}
	expires, _ := toFloat(rec["expiresAt"])
	if expires < float64(s.Now().UnixNano())/1e9 {
		return nil, protocolError("PREVIEW_EXPIRED", "Preview approval expired; preview the action again", nil)
	}
	if asString(rec["actionOperation"]) != action {
		return nil, protocolError("PREVIEW_ACTION_MISMATCH", "Preview approval belongs to a different action", nil)
	}
	expected := asString(rec["payloadHash"])
	if ph != expected || bindingHash(action, payload) != expected {
		return nil, protocolError("PREVIEW_PAYLOAD_CHANGED", "Action payload changed after preview; preview again", nil)
	}
	if rr != asString(rec["resourceRevision"]) {
		return nil, protocolError("PREVIEW_REVISION_MISMATCH", "Preview resource revision does not match the approved preview", nil)
	}
	return rec, nil
}
func toFloat(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case json.Number:
		f, e := x.Float64()
		return f, e == nil
	case int:
		return float64(x), true
	case int64:
		return float64(x), true
	}
	return 0, false
}

func ActionForPreview(op string, payload map[string]any) string {
	switch op {
	case "install.preview":
		return "install.run"
	case "chroots.remove":
		return "chroots.remove.execute"
	case "chroots.lifecycle.preview":
		switch strings.TrimSpace(asString(payload["action"])) {
		case "start":
			return "chroots.start"
		case "restart":
			return "chroots.restart"
		case "upgrade":
			return "chroots.upgrade"
		case "remove":
			return "chroots.remove.execute"
		}
	case "snapshots.preview":
		return map[string]string{"create": "snapshots.create", "restore": "snapshots.restore", "export": "snapshots.export"}[strings.TrimSpace(asString(payload["action"]))]
	case "users.preview":
		a := strings.ReplaceAll(strings.TrimSpace(asString(payload["action"])), "-", "_")
		return map[string]string{"add": "users.add", "remove": "users.remove", "sync_uid_gid": "users.sync_uid_gid", "set_shell": "users.set_shell", "set_sudo": "users.set_sudo", "set_password": "users.set_password", "password": "users.set_password"}[a]
	case "services.preview":
		a := strings.TrimSpace(asString(payload["action"]))
		if a == "start" || a == "stop" || a == "restart" || a == "enable" || a == "disable" {
			return "services." + a
		}
	case "smoke.preview":
		return "smoke.run"
	case "catalog.preview":
		return "catalog.apply"
	case "chroots.export", "transfer.preview_export":
		return "transfer.export"
	case "transfer.import_preview":
		return "transfer.import"
	case "artifacts.cleanup_preview":
		return "artifacts.cleanup"
	case "support.preview":
		return "support.bundle"
	case "system.module_build_preview":
		return "system.module_build"
	case "repair.preview":
		return "repair.apply"
	case "cleanup.temp_preview":
		return "cleanup.temp"
	}
	return ""
}
func PreviewForAction(action string, payload map[string]any, preferred string) (string, map[string]any, bool) {
	clean := map[string]any{}
	for k, v := range payload {
		if k == "previewId" || k == "payloadHash" || k == "resourceRevision" || k == "action" || k == "confirmation" || k == "confirmName" || k == "confirmUsername" || k == "title" {
			continue
		}
		clean[k] = v
	}
	if action == "chroots.remove.execute" && preferred == "chroots.lifecycle.preview" {
		clean["action"] = "remove"
		return preferred, clean, true
	}
	if action == "transfer.export" && preferred == "chroots.export" {
		return preferred, clean, true
	}
	mapping := map[string][2]string{"install.run": {"install.preview", ""}, "chroots.start": {"chroots.lifecycle.preview", "start"}, "chroots.restart": {"chroots.lifecycle.preview", "restart"}, "chroots.upgrade": {"chroots.lifecycle.preview", "upgrade"}, "chroots.remove.execute": {"chroots.remove", ""}, "snapshots.create": {"snapshots.preview", "create"}, "snapshots.restore": {"snapshots.preview", "restore"}, "snapshots.export": {"snapshots.preview", "export"}, "users.add": {"users.preview", "add"}, "users.remove": {"users.preview", "remove"}, "users.sync_uid_gid": {"users.preview", "sync_uid_gid"}, "users.set_shell": {"users.preview", "set_shell"}, "users.set_sudo": {"users.preview", "set_sudo"}, "users.set_password": {"users.preview", "set_password"}, "services.start": {"services.preview", "start"}, "services.stop": {"services.preview", "stop"}, "services.restart": {"services.preview", "restart"}, "services.enable": {"services.preview", "enable"}, "services.disable": {"services.preview", "disable"}, "smoke.run": {"smoke.preview", ""}, "catalog.apply": {"catalog.preview", ""}, "transfer.import": {"transfer.import_preview", ""}, "transfer.export": {"transfer.preview_export", ""}, "artifacts.cleanup": {"artifacts.cleanup_preview", ""}, "support.bundle": {"support.preview", ""}, "system.module_build": {"system.module_build_preview", ""}, "repair.apply": {"repair.preview", ""}, "cleanup.temp": {"cleanup.temp_preview", ""}}
	x, ok := mapping[action]
	if !ok {
		return "", nil, false
	}
	if x[1] != "" {
		clean["action"] = x[1]
	}
	return x[0], clean, true
}
