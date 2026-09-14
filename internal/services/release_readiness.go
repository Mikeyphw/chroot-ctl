package services

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

type ReleaseReadinessService struct{ C *Container }
type readinessRequirement struct{ ID, Label string }

const releaseEvidenceSchemaVersion = 3

var readinessRequirements = []readinessRequirement{
	{"go_test", "Go test suite"}, {"go_vet", "Go vet"}, {"go_contracts", "Go contract seal"}, {"repo_purity", "Go-only repository purity"}, {"audit_coverage", "Audit coverage ledger"},
	{"source_package", "Source package validator"}, {"android_compileDebugKotlin", "Android compileDebugKotlin"}, {"android_testDebugUnitTest", "Android testDebugUnitTest"}, {"android_lint_configuration_seal", "Android lint configuration seal"},
	{"module_render", "Module render/tree validator"}, {"module_zip", "Module ZIP validator"}, {"module_shell", "Module shell contract"}, {"source_no_webui", "Retired WebUI regression scan"},
}
var oidRE = regexp.MustCompile(`^[0-9a-f]{40}$`)
var shaRE = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (s *ReleaseReadinessService) EvidencePath() string {
	if p := strings.TrimSpace(os.Getenv("CHROOTCTL_VALIDATION_RESULTS")); p != "" {
		if a, e := filepath.Abs(p); e == nil {
			return a
		}
		return p
	}
	return filepath.Join(filepath.Dir(s.C.BaseConfig.DatabasePath), "validation-results.json")
}
func finiteNumber(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, !math.IsInf(x, 0) && !math.IsNaN(x)
	case float32:
		y := float64(x)
		return y, !math.IsInf(y, 0) && !math.IsNaN(y)
	case int:
		return float64(x), true
	case int64:
		return float64(x), true
	case json.Number:
		y, e := x.Float64()
		return y, e == nil && !math.IsInf(y, 0) && !math.IsNaN(y)
	}
	return 0, false
}
func stringValue(v any) string {
	if v == nil {
		return ""
	}
	s := fmt.Sprint(v)
	if s == "<nil>" {
		return ""
	}
	return s
}
func nilIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}
func requiredIDs() map[string]bool {
	m := map[string]bool{}
	for _, r := range readinessRequirements {
		m[r.ID] = true
	}
	return m
}

func readEvidence(path string) (map[string]any, string) {
	st, e := os.Lstat(path)
	if e != nil || !st.Mode().IsRegular() || st.Mode()&os.ModeSymlink != 0 {
		return map[string]any{}, "validation evidence is missing"
	}
	if st.Mode().Perm()&0077 != 0 {
		return map[string]any{}, "validation evidence permissions must not grant group/other access"
	}
	f, e := os.Open(path)
	if e != nil {
		return map[string]any{}, "validation evidence is unreadable"
	}
	defer f.Close()
	dec := json.NewDecoder(f)
	dec.UseNumber()
	payload := map[string]any{}
	if e = dec.Decode(&payload); e != nil {
		return map[string]any{}, "validation evidence is unreadable"
	}
	schema, ok := finiteNumber(payload["schemaVersion"])
	if !ok || int(schema) != releaseEvidenceSchemaVersion {
		return map[string]any{}, fmt.Sprintf("validation evidence schemaVersion must be %d", releaseEvidenceSchemaVersion)
	}
	if strings.TrimSpace(stringValue(payload["validationRunId"])) == "" {
		return map[string]any{}, "validation evidence validationRunId is required"
	}
	generated, ok := finiteNumber(payload["generatedAt"])
	if !ok || generated <= 0 {
		return map[string]any{}, "validation evidence generatedAt must be a finite positive timestamp"
	}
	commit, tree := stringValue(payload["sourceCommit"]), stringValue(payload["sourceTree"])
	if (commit == "") != (tree == "") {
		return map[string]any{}, "validation evidence sourceCommit/sourceTree must both be present or both be empty"
	}
	if commit != "" && (!oidRE.MatchString(commit) || !oidRE.MatchString(tree)) {
		return map[string]any{}, "validation evidence Git identities must be exact lowercase 40-hex object ids"
	}
	if !shaRE.MatchString(stringValue(payload["compatibilityManifestSha256"])) {
		return map[string]any{}, "validation evidence compatibilityManifestSha256 must be an exact lowercase SHA-256"
	}
	checks, ok := payload["checks"].(map[string]any)
	if !ok {
		return map[string]any{}, "validation evidence checks must be an object"
	}
	required := requiredIDs()
	missing, extra := []string{}, []string{}
	for id := range required {
		if _, ok := checks[id]; !ok {
			missing = append(missing, id)
		}
	}
	for id := range checks {
		if !required[id] {
			extra = append(extra, id)
		}
	}
	sort.Strings(missing)
	sort.Strings(extra)
	if len(missing) > 0 || len(extra) > 0 {
		return map[string]any{}, fmt.Sprintf("validation evidence check set mismatch; missing=%v extra=%v", missing, extra)
	}
	for id := range required {
		item, ok := checks[id].(map[string]any)
		if !ok {
			return map[string]any{}, fmt.Sprintf("validation evidence check %s must be an object", id)
		}
		status := strings.ToLower(stringValue(item["status"]))
		if status != "pass" && status != "fail" {
			return map[string]any{}, fmt.Sprintf("validation evidence check %s has invalid status %q", id, status)
		}
		if status == "pass" {
			code, cok := finiteNumber(item["exitCode"])
			recorded, rok := finiteNumber(item["recordedAt"])
			if !cok || int(code) != 0 || !rok || recorded <= 0 || strings.TrimSpace(stringValue(item["command"])) == "" {
				return map[string]any{}, fmt.Sprintf("validation evidence passing check %s has incomplete execution provenance", id)
			}
			prov := stringValue(item["provenance"])
			if prov != "subprocess" && prov != "internal-check" {
				return map[string]any{}, fmt.Sprintf("validation evidence passing check %s has invalid provenance", id)
			}
		}
	}
	return payload, ""
}

func findRepoRoot() string {
	cwd, e := os.Getwd()
	if e != nil {
		return ""
	}
	for p := cwd; ; p = filepath.Dir(p) {
		if exists(filepath.Join(p, "go.mod")) {
			return p
		}
		parent := filepath.Dir(p)
		if parent == p {
			break
		}
	}
	return ""
}
func gitValue(repo string, args ...string) string {
	if repo == "" || !exists(filepath.Join(repo, ".git")) {
		return ""
	}
	cmd := exec.Command("git", append([]string{"-C", repo}, args...)...)
	b, e := cmd.Output()
	if e != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}
func fileSHA(path string) string {
	st, e := os.Lstat(path)
	if e != nil || !st.Mode().IsRegular() || st.Mode()&os.ModeSymlink != 0 {
		return ""
	}
	b, e := os.ReadFile(path)
	if e != nil {
		return ""
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func (s *ReleaseReadinessService) compatibilityHash(repo string) string {
	candidates := []string{}
	if repo != "" {
		candidates = append(candidates, filepath.Join(repo, "docs/release/compatibility-manifest.json"))
	}
	if st := s.C.ModuleRuntime().Status(); st["active"] != nil {
		if a, ok := st["active"].(map[string]any); ok {
			candidates = append(candidates, filepath.Join(stringValue(a["path"]), "config/chrootctl/compatibility-manifest.json"))
		}
	}
	for _, p := range candidates {
		if v := fileSHA(p); v != "" {
			return v
		}
	}
	return ""
}
func (s *ReleaseReadinessService) identityProblem(payload map[string]any) string {
	repo := findRepoRoot()
	commit, tree := stringValue(payload["sourceCommit"]), stringValue(payload["sourceTree"])
	if repo != "" && exists(filepath.Join(repo, ".git")) && commit != "" {
		currentCommit := gitValue(repo, "rev-parse", "HEAD")
		currentTree := gitValue(repo, "rev-parse", "HEAD^{tree}")
		if currentCommit != commit || currentTree != tree {
			return "validation evidence does not match the current Git source identity"
		}
		if out, e := exec.Command("git", "-C", repo, "status", "--porcelain", "--untracked-files=normal").Output(); e != nil || strings.TrimSpace(string(out)) != "" {
			return "validation evidence requires an unchanged clean source worktree"
		}
	}
	expected := s.compatibilityHash(repo)
	if !shaRE.MatchString(expected) {
		return "validation evidence compatibility manifest identity cannot be verified"
	}
	if expected != stringValue(payload["compatibilityManifestSha256"]) {
		return "validation evidence compatibility manifest does not match the current runtime/source identity"
	}
	return ""
}
func (s *ReleaseReadinessService) Status() map[string]any {
	path := s.EvidencePath()
	payload, problem := readEvidence(path)
	if problem == "" {
		problem = s.identityProblem(payload)
		if problem != "" {
			payload = map[string]any{}
		}
	}
	raw, _ := payload["checks"].(map[string]any)
	checks := []map[string]any{}
	pass, fail, pending := 0, 0, 0
	for _, req := range readinessRequirements {
		item := map[string]any{}
		if v, ok := raw[req.ID].(map[string]any); ok {
			item = v
		}
		status := strings.ToLower(stringValue(item["status"]))
		if status == "" {
			status = "pending"
		}
		detail := stringValue(item["detail"])
		if status == "pass" {
			pass++
		} else if status == "fail" {
			fail++
		} else {
			pending++
			status = "pending"
			if detail == "" {
				detail = "No Go-native final-seal evidence recorded."
			}
		}
		checks = append(checks, map[string]any{"id": req.ID, "label": req.Label, "status": status, "detail": detail, "command": stringValue(item["command"]), "provenance": stringValue(item["provenance"]), "exitCode": item["exitCode"], "recordedAt": item["recordedAt"]})
	}
	// CHR08 makes unverified adaptive/localization readiness visible instead of
	// allowing Home to report a green release state. CHR20 owns the final proof.
	checks = append(checks, map[string]any{"id": "android_localization_rtl", "label": "Android localization/RTL proof", "status": "pending", "detail": "Final localization/RTL release evidence is required by CHR20."})
	pending++
	return map[string]any{"schemaVersion": releaseEvidenceSchemaVersion, "evidencePath": path, "evidencePresent": problem == "" && exists(path), "evidenceProblem": nilIfEmpty(problem), "generatedAt": payload["generatedAt"], "validationRunId": stringValue(payload["validationRunId"]), "sourceCommit": stringValue(payload["sourceCommit"]), "sourceTree": stringValue(payload["sourceTree"]), "checks": checks, "passCount": pass, "failCount": fail, "pendingCount": pending, "ready": fail == 0 && pending == 0 && pass == len(readinessRequirements)}
}
func (s *ReleaseReadinessService) Check(status map[string]any, id string) map[string]any {
	if rows, ok := status["checks"].([]map[string]any); ok {
		for _, r := range rows {
			if r["id"] == id {
				return r
			}
		}
	}
	return map[string]any{"id": id, "status": "pending", "detail": "No evidence recorded."}
}
