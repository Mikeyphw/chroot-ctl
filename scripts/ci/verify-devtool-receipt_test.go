//go:build ignore

package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeJSON(t *testing.T, path string, v any) {
	t.Helper()
	b, e := json.Marshal(v)
	if e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(path, b, 0600); e != nil {
		t.Fatal(e)
	}
}
func fixture(t *testing.T) (string, string, map[string]any, map[string]any) {
	t.Helper()
	dir := t.TempDir()
	pp := filepath.Join(dir, "plan.json")
	rp := filepath.Join(dir, "run.json")
	target := "chrootctl_hosted_release"
	wf := "ci-release"
	nodes := []map[string]any{}
	results := []map[string]any{}
	for _, id := range expectedStages {
		nodes = append(nodes, map[string]any{"key": target + "." + wf + "." + id, "target": target, "workflow": wf, "state": "passed", "result_count": 1})
		results = append(results, map[string]any{"status": "ok", "exit_code": 0})
	}
	p := map[string]any{"ok": true, "command": "plan", "exit_code": 0, "data": map[string]any{"action": wf, "targets": []string{target}, "summary": map[string]any{"node_count": 19, "target_local_job_count": 19, "repository_job_count": 0}}}
	r := map[string]any{"schema_version": 1, "machine_schema_version": 2, "ok": true, "command": "invoke", "repo": dir, "exit_code": 0, "totals": map[string]any{"failed": 0, "errors": 0, "skipped": 0}, "workflow": map[string]any{"targets": []string{target}, "workflows": []string{wf}, "nodes": nodes, "summary": map[string]any{"target_local_job_count": 19, "repository_job_count": 0}}, "results": results}
	writeJSON(t, pp, p)
	writeJSON(t, rp, r)
	return pp, rp, p, r
}
func TestCC12MachineReceiptsFullPass(t *testing.T) {
	p, r, _, _ := fixture(t)
	if err := validateReceipts(p, r, filepath.Dir(p)); err != nil {
		t.Fatal(err)
	}
}
func TestCC12MachineReceiptsRejectMisleadingData(t *testing.T) {
	for _, tc := range []string{"empty", "fake", "failed", "skipped", "incomplete", "wrong-job", "wrong-repo", "wrong-plan", "wrong-node-count", "result-failed"} {
		t.Run(tc, func(t *testing.T) {
			p, r, plan, run := fixture(t)
			switch tc {
			case "empty":
				os.WriteFile(r, nil, 0600)
			case "fake":
				os.WriteFile(r, []byte(`{}`), 0600)
			case "failed":
				run["ok"] = false
			case "skipped":
				run["totals"].(map[string]any)["skipped"] = 1
			case "incomplete":
				nodes := run["workflow"].(map[string]any)["nodes"].([]map[string]any)
				nodes[0]["state"] = "waiting"
			case "wrong-job":
				nodes := run["workflow"].(map[string]any)["nodes"].([]map[string]any)
				nodes[0]["key"] = strings.Repeat("x", 23)
			case "wrong-repo":
				run["repo"] = "/different/repo"
			case "wrong-plan":
				plan["data"].(map[string]any)["action"] = "ci-test"
			case "wrong-node-count":
				plan["data"].(map[string]any)["summary"].(map[string]any)["node_count"] = 18
			case "result-failed":
				run["results"].([]map[string]any)[0]["exit_code"] = 1
			}
			if tc != "empty" && tc != "fake" {
				writeJSON(t, r, run)
			}
			writeJSON(t, p, plan)
			if err := validateReceipts(p, r, filepath.Dir(p)); err == nil {
				t.Fatal("invalid Devtool evidence accepted")
			}
		})
	}
}
