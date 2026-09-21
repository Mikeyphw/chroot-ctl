package services

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	chmodule "chrootctl/internal/module"
)

const moduleID = "chrootctl-magisk"

type LifecycleService struct{ C *Container }
type ModuleRuntimeService struct{ C *Container }

func readKV(path string) map[string]string {
	out := map[string]string{}
	b, err := os.ReadFile(path)
	if err != nil {
		return out
	}
	for _, line := range strings.Split(string(b), "\n") {
		if line == "" || strings.HasPrefix(strings.TrimSpace(line), "#") {
			continue
		}
		p := strings.SplitN(line, "=", 2)
		if len(p) == 2 {
			out[strings.TrimSpace(p[0])] = strings.Trim(strings.TrimSpace(p[1]), "\"")
		}
	}
	return out
}
func moduleManager() string {
	if exists("/data/adb/ksu") {
		return "KernelSU"
	}
	if exists("/data/adb/magisk") {
		return "Magisk"
	}
	return "unknown"
}
func regularExecutable(path string) bool {
	st, e := os.Stat(path)
	return e == nil && st.Mode().IsRegular() && st.Mode()&0111 != 0
}

func manifestInt(v any) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case json.Number:
		i, _ := strconv.Atoi(n.String())
		return i
	case string:
		i, _ := strconv.Atoi(n)
		return i
	default:
		return 0
	}
}

func compatibilityReady(root string) bool {
	b, err := os.ReadFile(filepath.Join(root, "config/chrootctl/compatibility-manifest.json"))
	if err != nil {
		return false
	}
	var m map[string]any
	if json.Unmarshal(b, &m) != nil {
		return false
	}
	if manifestInt(m["schemaVersion"]) != 3 || manifestInt(m["bridgeProtocolVersion"]) != chmodule.BridgeProtocolVersion || stringValue(m["project"]) != "chrootctl" {
		return false
	}
	mod, _ := m["module"].(map[string]any)
	android, _ := m["androidApp"].(map[string]any)
	backend, _ := m["backend"].(map[string]any)
	runtime, _ := m["nativeRuntime"].(map[string]any)
	moduleVersionCode := manifestInt(mod["versionCode"])
	minimumBridge := manifestInt(mod["minimumSupportedBridgeProtocolVersion"])
	minimumModule := manifestInt(android["minimumSupportedModuleVersionCode"])
	return stringValue(mod["id"]) == moduleID && moduleVersionCode >= chmodule.ModuleVersionCode && minimumBridge >= 1 && minimumBridge <= chmodule.BridgeProtocolVersion &&
		stringValue(android["applicationId"]) == "com.mikeyphw.chrootctl" && manifestInt(android["versionCode"]) >= 1 && minimumModule >= 1 && minimumModule <= moduleVersionCode &&
		stringValue(backend["implementation"]) == "go" && stringValue(backend["version"]) == chmodule.BackendVersion &&
		manifestInt(runtime["schemaVersion"]) == chmodule.RuntimeSchemaVersion && stringValue(runtime["kind"]) == chmodule.RuntimeKind && stringValue(runtime["platform"]) == "android" && stringValue(runtime["abi"]) == chmodule.RuntimeABI && stringValue(runtime["entrypoint"]) == chmodule.RuntimeEntrypoint
}

func moduleStartupTargets(root string) []string {
	b, err := os.ReadFile(filepath.Join(root, "config/chrootctl/boot_targets.json"))
	if err != nil {
		return []string{}
	}
	var payload struct {
		StartupTargets []string `json:"startup_targets"`
	}
	if json.Unmarshal(b, &payload) != nil {
		return []string{}
	}
	out := make([]string, 0, len(payload.StartupTargets))
	seen := map[string]bool{}
	for _, raw := range payload.StartupTargets {
		v := strings.TrimSpace(raw)
		if v == "" || seen[v] {
			continue
		}
		seen[v] = true
		out = append(out, v)
	}
	return out
}

func (s *ModuleRuntimeService) candidate(root string, pending bool) map[string]any {
	prop := readKV(filepath.Join(root, "module.prop"))
	disabled := exists(filepath.Join(root, "disable"))
	removal := exists(filepath.Join(root, "remove"))
	required := []string{filepath.Join(root, "system/bin/chrootctl"), filepath.Join(root, "bin/chrootctl-magisk-helper"), filepath.Join(root, "config/chrootctl/compatibility-manifest.json"), filepath.Join(root, chmodule.ModulePackageManifestPath), filepath.Join(root, "runtime/arm64-v8a/runtime-manifest.json"), filepath.Join(root, "runtime/arm64-v8a/chrootctl")}
	layout := prop["id"] == moduleID
	layoutProblem := ""
	for _, p := range required {
		st, e := os.Lstat(p)
		if e != nil || st.Mode()&os.ModeSymlink != 0 || !st.Mode().IsRegular() {
			layout = false
			if layoutProblem == "" {
				layoutProblem = "required module file missing or unsafe: " + p
			}
		}
	}
	if layout {
		if err := chmodule.ValidateRendered(root); err != nil {
			layout = false
			layoutProblem = err.Error()
		}
	}
	compatOK := compatibilityReady(root)
	active := layout && compatOK && !pending && !disabled && !removal
	runtimeRoot := filepath.Join(root, "runtime", chmodule.RuntimeABI)
	runtimeErr := chmodule.ValidateRuntime(runtimeRoot)
	readiness := map[string]any{"ready": false, "mode": "bundled-native", "path": filepath.Join(runtimeRoot, "runtime-manifest.json"), "executable": filepath.Join(runtimeRoot, chmodule.RuntimeEntrypoint), "runtimeKind": chmodule.RuntimeKind, "abi": chmodule.RuntimeABI, "backendVersion": chmodule.BackendVersion, "bridgeProtocolVersion": chmodule.BridgeProtocolVersion, "packageManifest": filepath.Join(root, chmodule.ModulePackageManifestPath), "packageSealReady": layout && layoutProblem == ""}
	if active && runtimeErr == nil && regularExecutable(filepath.Join(runtimeRoot, chmodule.RuntimeEntrypoint)) {
		readiness["ready"] = true
		if b, e := os.ReadFile(filepath.Join(runtimeRoot, "runtime-manifest.json")); e == nil {
			var m map[string]any
			if json.Unmarshal(b, &m) == nil {
				for k, v := range m {
					readiness[k] = v
				}
			}
		}
	} else if layoutProblem != "" {
		readiness["reason"] = layoutProblem
	} else if runtimeErr != nil {
		readiness["reason"] = runtimeErr.Error()
	} else {
		readiness["reason"] = "native_runtime_entrypoint_missing_or_unsafe"
	}
	vc, _ := strconv.Atoi(prop["versionCode"])
	return map[string]any{"path": root, "exists": exists(root), "pending": pending, "active": active, "disabled": disabled, "pendingRemoval": removal, "hasModuleProp": exists(filepath.Join(root, "module.prop")), "layoutReady": layout, "packageSealReady": layout && layoutProblem == "", "sealProblem": nilIfEmpty(layoutProblem), "compatibility": map[string]any{"valid": compatOK, "legacy": false}, "id": prop["id"], "name": prop["name"], "version": prop["version"], "versionCode": vc, "startupTargets": moduleStartupTargets(root), "runtimeReadiness": readiness, "dependencyReadiness": readiness}
}
func (s *ModuleRuntimeService) Status() map[string]any {
	active := s.candidate("/data/adb/modules/"+moduleID, false)
	pending := []map[string]any{}
	for _, p := range []string{"/data/adb/modules_update/" + moduleID} {
		if exists(p) {
			pending = append(pending, s.candidate(p, true))
		}
	}
	usable, _ := active["active"].(bool)
	rr, _ := active["runtimeReadiness"].(map[string]any)
	ready, _ := rr["ready"].(bool)
	warnings := []string{}
	if !active["exists"].(bool) {
		warnings = append(warnings, "No installed chrootctl Magisk/KernelSU module was detected in /data/adb/modules.")
	} else if active["disabled"].(bool) {
		warnings = append(warnings, "The installed chrootctl module is disabled.")
	} else if !active["layoutReady"].(bool) {
		warnings = append(warnings, "The installed chrootctl module is missing required bundled-native runtime files.")
	}
	if len(pending) > 0 {
		warnings = append(warnings, "A pending module update exists and is intentionally excluded from runtime execution until reboot activation.")
	}
	if usable && !ready {
		warnings = append(warnings, "The active module bundled-native runtime seal is missing, stale, or invalid.")
	}
	var activeValue any
	if usable {
		activeValue = active
	}
	startupTargets, _ := active["startupTargets"].([]string)
	return map[string]any{"moduleId": moduleID, "installed": active["exists"], "active": activeValue, "installedState": active, "pendingUpdate": len(pending) > 0, "pending": pending, "ready": usable && ready, "manager": moduleManager(), "startupTargets": startupTargets, "warnings": warnings}
}
func (s *ModuleRuntimeService) ActiveExecutable() string {
	st := s.Status()
	a, ok := st["active"].(map[string]any)
	if !ok {
		return ""
	}
	rr, _ := a["runtimeReadiness"].(map[string]any)
	if ready, _ := rr["ready"].(bool); !ready {
		return ""
	}
	p := "/data/adb/modules/" + moduleID + "/system/bin/chrootctl"
	if regularExecutable(p) {
		return p
	}
	return ""
}

func (s *LifecycleService) RuntimeMode() map[string]any {
	m := s.C.ModuleRuntime().Status()
	if _, e := os.Stat("/data/adb/chrootctl"); e == nil && m["active"] != nil {
		return map[string]any{"id": "magisk", "label": m["manager"].(string) + " module", "privileged": true, "control_accessible": true}
	}
	return map[string]any{"id": "standalone", "label": "Standalone Go executable", "privileged": false, "control_accessible": false}
}
func (s *LifecycleService) BackendStatus() map[string]any {
	m := s.C.ModuleRuntime().Status()
	out := map[string]any{"binary": nil, "implementation": "go", "version": nil, "ready": false, "reason": "module_missing", "readiness_file": nil, "runtime_kind": nil, "abi": nil}
	if a, ok := m["active"].(map[string]any); ok {
		if rr, ok := a["runtimeReadiness"].(map[string]any); ok {
			out["binary"] = rr["executable"]
			out["version"] = rr["backendVersion"]
			out["ready"] = rr["ready"]
			out["reason"] = rr["reason"]
			out["readiness_file"] = rr["path"]
			out["runtime_kind"] = rr["runtimeKind"]
			out["abi"] = rr["abi"]
		}
	}
	return out
}
func (s *LifecycleService) Status() map[string]any {
	m := s.C.ModuleRuntime().Status()
	_, enabledErr := os.Stat("/data/adb/chrootctl/android-app.enabled")
	return map[string]any{"running": m["active"] != nil, "state": "android_app_primary", "control_file": "/data/adb/chrootctl/control.state", "enabled": enabledErr == nil, "mode": s.RuntimeMode(), "module": m, "backend": s.BackendStatus(), "logs": map[string]string{"module": "/data/adb/modules/" + moduleID + "/var/log/chrootctl.log", "install": "/data/adb/modules/" + moduleID + "/runtime/arm64-v8a/runtime-manifest.json", "dependencies": "/data/adb/modules/" + moduleID + "/runtime/arm64-v8a/runtime-manifest.json"}, "checked_at": time.Now().Unix()}
}
