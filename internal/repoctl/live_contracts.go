package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"

	"chrootctl/internal/bridge"
	"chrootctl/internal/cli"
	"chrootctl/internal/contracts"
)

type frozenCLIFile struct {
	GlobalArguments       []frozenArgument `json:"globalArguments"`
	CommandNodes          []frozenCLINode  `json:"commandNodes"`
	AppBridgeCommandNodes []frozenCLINode  `json:"appBridgeCommandNodes"`
}

type frozenCLINode struct {
	Path        []string         `json:"path"`
	Command     string           `json:"command"`
	Description *string          `json:"description"`
	Epilog      *string          `json:"epilog"`
	Arguments   []frozenArgument `json:"arguments"`
}

type frozenArgument struct {
	Dest          string   `json:"dest"`
	OptionStrings []string `json:"optionStrings"`
	Action        string   `json:"action"`
	NArgs         any      `json:"nargs"`
	Default       any      `json:"default"`
	Choices       []string `json:"choices"`
	Type          *string  `json:"type"`
	Required      bool     `json:"required"`
	Help          *string  `json:"help"`
}

func normalizeJSONNumber(v any) any {
	switch n := v.(type) {
	case float64:
		if n == float64(int64(n)) {
			return int64(n)
		}
	case int:
		return int64(n)
	case int32:
		return int64(n)
	case int64:
		return n
	}
	return v
}

func liveArgument(a cli.ArgumentSpec) frozenArgument {
	var typ *string
	if a.Type != "" {
		v := a.Type
		typ = &v
	}
	var help *string
	if a.Help != "" {
		v := a.Help
		help = &v
	}
	choices := append([]string(nil), a.Choices...)
	if len(choices) == 0 {
		choices = nil
	}
	return frozenArgument{
		Dest:          a.Dest,
		OptionStrings: append([]string(nil), a.Options...),
		Action:        a.Action,
		NArgs:         normalizeJSONNumber(a.NArgs),
		Default:       normalizeJSONNumber(a.Default),
		Choices:       choices,
		Type:          typ,
		Required:      a.Required,
		Help:          help,
	}
}

func normalizeFrozenArgument(a frozenArgument) frozenArgument {
	a.NArgs = normalizeJSONNumber(a.NArgs)
	a.Default = normalizeJSONNumber(a.Default)
	if len(a.OptionStrings) == 0 {
		a.OptionStrings = nil
	}
	if len(a.Choices) == 0 {
		a.Choices = nil
	}
	return a
}

func validateLiveCLI(root string) error {
	raw, err := os.ReadFile(filepath.Join(root, "migration", "contracts", "v1", "cli.json"))
	if err != nil {
		return err
	}
	var frozen frozenCLIFile
	if err = json.Unmarshal(raw, &frozen); err != nil {
		return err
	}
	if len(frozen.CommandNodes) != len(cli.CommandSpecs) {
		return fmt.Errorf("live CLI node drift: fixture=%d live=%d", len(frozen.CommandNodes), len(cli.CommandSpecs))
	}
	for i, want := range frozen.CommandNodes {
		got := cli.CommandSpecs[i]
		if want.Command != got.Command || !reflect.DeepEqual(want.Path, got.Path) {
			return fmt.Errorf("live CLI command drift at node %d: fixture=%q live=%q", i, want.Command, got.Command)
		}
		wantDesc, wantEpilog := "", ""
		if want.Description != nil {
			wantDesc = *want.Description
		}
		if want.Epilog != nil {
			wantEpilog = *want.Epilog
		}
		if wantDesc != got.Description || wantEpilog != got.Epilog {
			return fmt.Errorf("live CLI text drift for %s", want.Command)
		}
		if len(want.Arguments) != len(got.Arguments) {
			return fmt.Errorf("live CLI argument-count drift for %s: fixture=%d live=%d", want.Command, len(want.Arguments), len(got.Arguments))
		}
		for j := range want.Arguments {
			wa := normalizeFrozenArgument(want.Arguments[j])
			ga := liveArgument(got.Arguments[j])
			if !reflect.DeepEqual(wa, ga) {
				return fmt.Errorf("live CLI argument drift for %s argument %d (%s)", want.Command, j, wa.Dest)
			}
		}
	}
	if len(frozen.GlobalArguments) != len(cli.GlobalArguments) {
		return fmt.Errorf("live global CLI argument-count drift: fixture=%d live=%d", len(frozen.GlobalArguments), len(cli.GlobalArguments))
	}
	for i := range frozen.GlobalArguments {
		if !reflect.DeepEqual(normalizeFrozenArgument(frozen.GlobalArguments[i]), liveArgument(cli.GlobalArguments[i])) {
			return fmt.Errorf("live global CLI argument drift at %d (%s)", i, frozen.GlobalArguments[i].Dest)
		}
	}
	return validateAppBridgeCLI(frozen.AppBridgeCommandNodes)
}

func validateAppBridgeCLI(nodes []frozenCLINode) error {
	seen := map[string]bool{}
	for _, node := range nodes {
		name := strings.TrimPrefix(node.Command, "app ")
		if name == node.Command || name == "" {
			return fmt.Errorf("invalid frozen app bridge command %q", node.Command)
		}
		seen[name] = true
		var args []string
		switch name {
		case "capabilities", "state":
			args = []string{name}
		case "query", "preview":
			args = []string{name}
		case "run":
			args = []string{name, "--events", "ndjson"}
		case "operation", "cancel", "reconcile":
			args = []string{name, "contract-operation-id"}
		default:
			return fmt.Errorf("frozen app bridge command has no live parser case: %s", name)
		}
		opts, err := bridge.ParseAppArgs(args)
		if err != nil || opts.Command != name {
			return fmt.Errorf("live app bridge parser drift for %s: %v", name, err)
		}
		if (name == "query" || name == "preview" || name == "run") && opts.RequestFile != "-" {
			return fmt.Errorf("live app bridge default request-file drift for %s", name)
		}
		if name == "run" && opts.Events != "ndjson" {
			return fmt.Errorf("live app bridge event encoding drift: %q", opts.Events)
		}
	}
	if len(seen) != contracts.ExpectedAppBridgeCommandNodeCount {
		return fmt.Errorf("live app bridge command-count drift: %d", len(seen))
	}
	return nil
}

func validateLiveBridge(bundle contracts.Bundle) error {
	live := bridge.ContractSpecs()
	if len(live) != len(bundle.Bridge.Operations) {
		return fmt.Errorf("live bridge operation-count drift: fixture=%d live=%d", len(bundle.Bridge.Operations), len(live))
	}
	for i, want := range bundle.Bridge.Operations {
		got := live[i]
		fields := make([]string, 0, len(got.PayloadFields))
		for field := range got.PayloadFields {
			fields = append(fields, field)
		}
		sort.Strings(fields)
		if len(fields) == 0 {
			fields = nil
		}
		wantFields := append([]string(nil), want.PayloadFields...)
		sort.Strings(wantFields)
		if len(wantFields) == 0 {
			wantFields = nil
		}
		if want.Name != got.Name || want.Mode != got.Mode || want.Description != got.Description || want.Destructive != got.Destructive || want.LockScope != got.LockScope || !reflect.DeepEqual(wantFields, fields) {
			return fmt.Errorf("live bridge metadata drift for operation %d: fixture=%s live=%s", i, want.Name, got.Name)
		}
	}
	return nil
}

// ValidateLiveContracts proves that the currently compiled CLI and bridge still
// implement the frozen GO00/GO10/GO11 surfaces. Validating fixture counts alone
// is insufficient because generated/live metadata could otherwise drift.
func ValidateLiveContracts(root string, bundle contracts.Bundle) error {
	if err := validateLiveCLI(root); err != nil {
		return err
	}
	return validateLiveBridge(bundle)
}
