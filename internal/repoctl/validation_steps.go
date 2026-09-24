package repoctl

import (
	"fmt"
	"path/filepath"

	"chrootctl/internal/contractgen"
	"chrootctl/internal/contracts"
	"chrootctl/internal/testseal"
)

type sourceValidationStep struct {
	Name string
	Run  func(string) error
}

var sourceValidationSteps = []sourceValidationStep{
	{Name: "test-seal", Run: func(root string) error { return testseal.Validate(root, false) }},
	{Name: "repository-purity", Run: ValidateRepositoryPurity},
	{Name: "audit-coverage", Run: ValidateAuditCoverage},
	{Name: "root-module-retirement", Run: ValidateRootModuleRetirement},
	{Name: "contract-generation", Run: contractgen.Check},
	{Name: "cli-contract", Run: ValidateCLIContractFoundation},
	{Name: "mutation-engine", Run: ValidateMutationEngineGateA},
	{Name: "crud-atomicity", Run: ValidateCRUDAtomicity},
	{Name: "clipboard-integration", Run: ValidateClipboardPrivilegedIntegration},
	{Name: "frozen-live-contracts", Run: func(root string) error {
		bundle, err := contracts.LoadDir(filepath.Join(root, "migration", "contracts", "v1"))
		if err != nil {
			return err
		}
		if err = bundle.Validate(); err != nil {
			return err
		}
		return ValidateLiveContracts(root, bundle)
	}},
}

// ValidationStepNames returns the stable source-gate identifiers used by
// Devtool workflows.  The names are intentionally independent of EXO internals:
// repoctl owns repository semantics while Devtool owns orchestration/telemetry.
func ValidationStepNames() []string {
	out := make([]string, 0, len(sourceValidationSteps))
	for _, step := range sourceValidationSteps {
		out = append(out, step.Name)
	}
	return out
}

// ValidateStep runs one current, non-retired repository source gate.
func ValidateStep(name string) error {
	root, err := repoRoot()
	if err != nil {
		return err
	}
	for _, step := range sourceValidationSteps {
		if step.Name == name {
			return step.Run(root)
		}
	}
	return fmt.Errorf("unknown validation step %q", name)
}

func validateSourceContracts() error {
	root, err := repoRoot()
	if err != nil {
		return err
	}
	for _, step := range sourceValidationSteps {
		if err = step.Run(root); err != nil {
			return fmt.Errorf("validation step %s: %w", step.Name, err)
		}
	}
	return nil
}
