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

var readinessRequirements = []readinessRequirement{
	{"python_pytest", "Python pytest"}, {"python_mypy", "Python mypy"}, {"python_compileall", "Python compileall"},
	{"android_contract_validators", "Android source-contract validators"}, {"source_package", "Source package validator"},
	{"android_compileDebugKotlin", "Android compileDebugKotlin"}, {"android_testDebugUnitTest", "Android testDebugUnitTest"}, {"android_lintDebug", "Android lintDebug"},
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
	if !ok || int(schema) != 2 {
		return map[string]any{}, "validation evidence schemaVersion must be 2"
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
	generated, gok := finiteNumber(payload["generatedAt"])
	started, sok := finiteNumber(payload["validationStartedAt"])
	completed, cok := finiteNumber(payload["validationCompletedAt"])
	if !gok {
		return map[string]any{}, "validation evidence generatedAt must be a finite timestamp"
	}
	if !sok {
		return map[string]any{}, "validation evidence validationStartedAt must be a finite timestamp"
	}
	if !cok {
		return map[string]any{}, "validation evidence validationCompletedAt must be a finite timestamp"
	}
	if completed < started || generated != completed {
		return map[string]any{}, "validation evidence run timestamps are inconsistent"
	}
	if strings.TrimSpace(stringValue(payload["validationRunId"])) == "" {
		return map[string]any{}, "validation evidence validationRunId is required"
	}
	for _, k := range []string{"sourceCommit", "sourceTree", "validatedTree"} {
		if !oidRE.MatchString(stringValue(payload[k])) {
			return map[string]any{}, fmt.Sprintf("validation evidence %s must be an exact lowercase 40-hex Git object id", k)
		}
	}
	if payload["sourceTree"] == payload["validatedTree"] {
		return map[string]any{}, "validation evidence validatedTree must differ from the pre-overlay sourceTree"
	}
	if !shaRE.MatchString(stringValue(payload["compatibilityManifestSha256"])) {
		return map[string]any{}, "validation evidence compatibilityManifestSha256 must be an exact lowercase SHA-256"
	}
	for id := range required {
		item, ok := checks[id].(map[string]any)
		if !ok {
			return map[string]any{}, fmt.Sprintf("validation evidence check %s must be an object", id)
		}
		if strings.ToLower(stringValue(item["status"])) != "pass" {
			continue
		}
		gs, a := finiteNumber(item["startedAt"])
		gf, b := finiteNumber(item["finishedAt"])
		ra, c := finiteNumber(item["recordedAt"])
		if !a || !b || !c {
			return map[string]any{}, fmt.Sprintf("validation evidence passing check %s has invalid timing provenance", id)
		}
		if !(started <= gs && gs <= gf && gf <= completed && gf <= ra && ra <= completed) {
			return map[string]any{}, fmt.Sprintf("validation evidence passing check %s has inconsistent timing provenance", id)
		}
		prov := stringValue(item["provenance"])
		if prov == "deduplicated-subprocess" {
			parent := stringValue(item["derivedFrom"])
			if !required[parent] || parent == id {
				return map[string]any{}, fmt.Sprintf("validation evidence passing check %s has invalid derivedFrom provenance", id)
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
		if exists(filepath.Join(p, ".git")) {
			return p
		}
		parent := filepath.Dir(p)
		if parent == p {
			break
		}
	}
	return ""
}
func gitValue(repo string, env []string, args ...string) string {
	if repo == "" {
		return ""
	}
	cmd := exec.Command("git", append([]string{"-C", repo}, args...)...)
	if env != nil {
		cmd.Env = env
	}
	b, e := cmd.Output()
	if e != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}
func worktreeTree(repo string) string {
	if repo == "" {
		return ""
	}
	f, e := os.CreateTemp("", "chrootctl-readiness-index-*")
	if e != nil {
		return ""
	}
	name := f.Name()
	f.Close()
	os.Remove(name)
	defer os.Remove(name)
	env := append(os.Environ(), "GIT_INDEX_FILE="+name)
	cmd := exec.Command("git", "-C", repo, "read-tree", "HEAD")
	cmd.Env = env
	if e = cmd.Run(); e != nil {
		return ""
	}
	cmd = exec.Command("git", "-C", repo, "add", "-A", "--", ".")
	cmd.Env = env
	if e = cmd.Run(); e != nil {
		return ""
	}
	return gitValue(repo, env, "write-tree")
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
	recordedCommit := stringValue(payload["sourceCommit"])
	recordedSourceTree := stringValue(payload["sourceTree"])
	recordedValidatedTree := stringValue(payload["validatedTree"])
	if repo != "" {
		currentCommit := gitValue(repo, nil, "rev-parse", "HEAD")
		if !oidRE.MatchString(currentCommit) {
			return "validation evidence source identity cannot be verified because Git HEAD is unavailable"
		}
		if gitValue(repo, nil, "rev-parse", recordedCommit+"^{tree}") != recordedSourceTree {
			return "validation evidence sourceCommit does not resolve to the recorded pre-overlay sourceTree"
		}
		if wt := worktreeTree(repo); !oidRE.MatchString(wt) || wt != recordedValidatedTree {
			return "validation evidence validatedTree does not match the exact current tracked/untracked worktree"
		}
		currentTree := gitValue(repo, nil, "rev-parse", "HEAD^{tree}")
		if currentCommit == recordedCommit {
			if currentTree != recordedSourceTree {
				return "validation evidence pre-commit HEAD tree does not match the recorded sourceTree"
			}
		} else {
			parent := gitValue(repo, nil, "rev-parse", "HEAD^")
			if parent != recordedCommit || currentTree != recordedValidatedTree {
				return fmt.Sprintf("validation evidence belongs to source commit %s, current checkout is %s, and it is not the single Devtool commit of the exact validated tree", recordedCommit, currentCommit)
			}
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
		if status != "pass" && status != "fail" && status != "warn" && status != "pending" {
			status = "fail"
		}
		detail := stringValue(item["detail"])
		if status == "pass" {
			prov := stringValue(item["provenance"])
			code, ok := finiteNumber(item["exitCode"])
			cmd := strings.TrimSpace(stringValue(item["command"]))
			if _, ok2 := finiteNumber(item["recordedAt"]); !ok2 {
				status = "fail"
				detail = "Passing evidence is missing recordedAt."
			} else if !ok || int(code) != 0 {
				status = "fail"
				detail = "Passing evidence is missing a proven exitCode 0."
			} else if prov != "subprocess" && prov != "deduplicated-subprocess" {
				status = "fail"
				detail = "Passing evidence has invalid provenance."
			} else if cmd == "" {
				status = "fail"
				detail = "Passing evidence is missing command/task provenance."
			}
		}
		if status == "pending" && detail == "" {
			detail = "No final-seal evidence recorded."
		}
		switch status {
		case "pass":
			pass++
		case "fail":
			fail++
		default:
			pending++
		}
		checks = append(checks, map[string]any{"id": req.ID, "label": req.Label, "status": status, "detail": detail, "command": stringValue(item["command"]), "provenance": stringValue(item["provenance"]), "exitCode": item["exitCode"], "recordedAt": item["recordedAt"]})
	}
	return map[string]any{"schemaVersion": 2, "evidencePath": path, "evidencePresent": problem == "" && exists(path), "evidenceProblem": nilIfEmpty(problem), "generatedAt": payload["generatedAt"], "validationRunId": stringValue(payload["validationRunId"]), "sourceCommit": stringValue(payload["sourceCommit"]), "sourceTree": stringValue(payload["sourceTree"]), "validatedTree": stringValue(payload["validatedTree"]), "checks": checks, "passCount": pass, "failCount": fail, "pendingCount": pending, "ready": fail == 0 && pending == 0 && pass == len(readinessRequirements)}
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
