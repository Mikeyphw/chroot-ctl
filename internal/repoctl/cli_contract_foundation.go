package repoctl

import (
	"fmt"
	"strings"

	"chrootctl/internal/cli"
	"chrootctl/internal/clicontract"
	"chrootctl/internal/completion"
)

// ValidateCLIContractFoundation is the executable CHR02 seal. It checks the
// invariants that previously drifted independently across parser/help/JSON,
// completion, privilege policy, and generated documentation.
func ValidateCLIContractFoundation(root string) error {
	if len(cli.CommandSpecs) != 83 {
		return fmt.Errorf("CHR02 command count: got %d want 83", len(cli.CommandSpecs))
	}
	if len(cli.GlobalArguments) != 8 {
		return fmt.Errorf("CHR02 global count: got %d want 8", len(cli.GlobalArguments))
	}
	seen := map[string]bool{}
	for _, spec := range cli.CommandSpecs {
		if seen[spec.Command] {
			return fmt.Errorf("CHR02 duplicate command: %s", spec.Command)
		}
		seen[spec.Command] = true
		if strings.TrimSpace(spec.Handler) == "" {
			return fmt.Errorf("CHR02 command has no handler metadata: %s", spec.Command)
		}
		if len(spec.OutputModes) == 0 {
			return fmt.Errorf("CHR02 command has no output mode: %s", spec.Command)
		}
		for _, mode := range spec.OutputModes {
			if mode != "human" && mode != "json" && mode != "raw" && mode != "bridge" {
				return fmt.Errorf("CHR02 invalid output mode %q for %s", mode, spec.Command)
			}
		}
	}
	if !seen["version"] {
		return fmt.Errorf("CHR02 version command missing")
	}
	if clicontract.ContractSHA256 == "" {
		return fmt.Errorf("CHR02 generated contract has no source digest")
	}

	cases := []struct {
		name    string
		args    []string
		wantErr bool
	}{
		{"globals-after-command", []string{"status", "--json", "--name=demo"}, false},
		{"help-skips-required", []string{"magisk", "render", "--help"}, false},
		{"exclusive-actions", []string{"start", "--login", "--root-login"}, true},
		{"bounded-integer", []string{"events", "list", "--limit", "1001"}, true},
		{"early-json-guard", []string{"completion", "zsh", "--json"}, true},
		{"version-global", []string{"--json", "--version"}, false},
	}
	for _, tc := range cases {
		_, err := cli.Parse(tc.args)
		if (err != nil) != tc.wantErr {
			return fmt.Errorf("CHR02 parser invariant %s: args=%v err=%v", tc.name, tc.args, err)
		}
	}
	inv, err := cli.Parse([]string{"run", "--list"})
	if err != nil {
		return err
	}
	if got := inv.Spec.EffectivePrivilege(inv.Values); got != "none" {
		return fmt.Errorf("CHR02 run --list privilege=%s want none", got)
	}
	zsh, err := completion.GenerateZsh()
	if err != nil {
		return err
	}
	for _, token := range []string{"transfer", "events", "support-bundle", "clipboard", "magisk", "version"} {
		if !strings.Contains(zsh, token) {
			return fmt.Errorf("CHR02 completion missing %s", token)
		}
	}
	return nil
}
