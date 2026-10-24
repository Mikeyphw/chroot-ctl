//go:build ignore

// CC12: verify the semantics of the reviewed Devtool's machine/run receipts.
// This is a source-contract gate, not an external attestation.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
)

var expectedStages = []string{
	"preflight",
	"restore-go",
	"restore-tmux",
	"build-tmux",
	"verify-tmux",
	"build-rclone",
	"build-repoctl",
	"test-webui",
	"test-go",
	"test-tmux",
	"lint-native",
	"lint-go",
	"test-verifier",
	"test-skybind-consumer",
	"test-edition-upgrade",
	"test-source",
	"build-editions",
	"verify-editions",
	"receipt",
}

func decode(path string, target any) error {
	bytes, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(bytes, target)
}

type node struct {
	Key         string `json:"key"`
	Target      string `json:"target"`
	Workflow    string `json:"workflow"`
	State       string `json:"state"`
	ResultCount int    `json:"result_count"`
}

type receipt struct {
	SchemaVersion        int    `json:"schema_version"`
	MachineSchemaVersion int    `json:"machine_schema_version"`
	OK                   bool   `json:"ok"`
	Command              string `json:"command"`
	Repo                 string `json:"repo"`
	ExitCode             int    `json:"exit_code"`
	Totals               struct {
		Failed  int `json:"failed"`
		Errors  int `json:"errors"`
		Skipped int `json:"skipped"`
	} `json:"totals"`
	Workflow struct {
		Targets   []string `json:"targets"`
		Workflows []string `json:"workflows"`
		Nodes     []node   `json:"nodes"`
		Summary   struct {
			TargetLocalJobCount int `json:"target_local_job_count"`
			RepositoryJobCount  int `json:"repository_job_count"`
		} `json:"summary"`
	} `json:"workflow"`
	Results []struct {
		Status   string `json:"status"`
		ExitCode int    `json:"exit_code"`
	} `json:"results"`
}

type plan struct {
	OK       bool   `json:"ok"`
	Command  string `json:"command"`
	ExitCode int    `json:"exit_code"`
	Data     struct {
		Action  string   `json:"action"`
		Targets []string `json:"targets"`
		Summary struct {
			NodeCount           int `json:"node_count"`
			TargetLocalJobCount int `json:"target_local_job_count"`
			RepositoryJobCount  int `json:"repository_job_count"`
		} `json:"summary"`
	} `json:"data"`
}

func validateReceipts(planPath, runPath, repo string) error {
	var p plan
	if err := decode(planPath, &p); err != nil {
		return fmt.Errorf("Devtool DAG plan: %w", err)
	}
	target := "chrootctl_hosted_release"
	workflow := "ci-release"
	if !p.OK || p.Command != "plan" || p.ExitCode != 0 || p.Data.Action != workflow ||
		len(p.Data.Targets) != 1 || p.Data.Targets[0] != target ||
		p.Data.Summary.NodeCount != len(expectedStages) ||
		p.Data.Summary.TargetLocalJobCount != len(expectedStages) || p.Data.Summary.RepositoryJobCount != 0 {
		return errors.New("Devtool DAG plan does not match the expected 19 target-local jobs")
	}
	var r receipt
	if err := decode(runPath, &r); err != nil {
		return fmt.Errorf("Devtool machine receipt: %w", err)
	}
	if r.SchemaVersion != 1 || r.MachineSchemaVersion < 2 || !r.OK || r.Command != "invoke" ||
		r.ExitCode != 0 || r.Totals.Failed != 0 || r.Totals.Errors != 0 || r.Totals.Skipped != 0 ||
		len(r.Workflow.Targets) != 1 || r.Workflow.Targets[0] != target ||
		len(r.Workflow.Workflows) != 1 || r.Workflow.Workflows[0] != workflow ||
		r.Workflow.Summary.TargetLocalJobCount != len(expectedStages) || r.Workflow.Summary.RepositoryJobCount != 0 ||
		len(r.Workflow.Nodes) != len(expectedStages) || len(r.Results) < len(expectedStages) {
		return errors.New("Devtool run is failed, incomplete, skipped, or not the expected hosted workflow")
	}
	if repo != "" {
		expected, err := filepath.Abs(repo)
		if err != nil {
			return err
		}
		actual, err := filepath.Abs(r.Repo)
		if err != nil || filepath.Clean(expected) != filepath.Clean(actual) {
			return errors.New("Devtool machine receipt repository identity mismatch")
		}
	}
	expectedNodes := make(map[string]bool)
	for _, n := range expectedStages {
		expectedNodes[target+"."+workflow+"."+n] = true
	}
	for _, n := range r.Workflow.Nodes {
		if !expectedNodes[n.Key] || n.Target != target || n.Workflow != workflow || n.State != "passed" || n.ResultCount < 1 {
			return fmt.Errorf("Devtool workflow node not proven passed: %s (%s)", n.Key, n.State)
		}
		delete(expectedNodes, n.Key)
	}
	if len(expectedNodes) != 0 {
		return errors.New("Devtool machine receipt missing required hosted nodes")
	}
	for i, result := range r.Results {
		if result.Status != "ok" || result.ExitCode != 0 {
			return fmt.Errorf("Devtool result %d is not successful: %s", i, result.Status)
		}
	}
	return nil
}

func main() {
	planPath := flag.String("plan", "", "Devtool plan JSON")
	runPath := flag.String("run", "", "Devtool machine execution JSON")
	repo := flag.String("repo", "", "expected Chrootctl repository root")
	flag.Parse()
	if *planPath == "" || *runPath == "" {
		fmt.Fprintln(os.Stderr, "--plan and --run required")
		os.Exit(2)
	}
	if err := validateReceipts(*planPath, *runPath, *repo); err != nil {
		fmt.Fprintln(os.Stderr, "FAIL_CC12_DEVTOOL_MACHINE_RECEIPT:", err)
		os.Exit(1)
	}
	fmt.Println("PASS_CC12_ALL_19_DEVTOOL_WORKFLOW_NODES_PASSED")
}
