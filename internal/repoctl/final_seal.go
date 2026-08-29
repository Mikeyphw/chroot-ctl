package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"chrootctl/internal/contracts"
	chmodule "chrootctl/internal/module"
	"chrootctl/internal/testseal"
)

type FinalSealOptions struct {
	WorkDir        string
	Jobs           int
	SkipValidation bool
}

type finalSealSummary struct {
	ContractSchema      int    `json:"contractSchema"`
	CommandNodes        int    `json:"commandNodes"`
	BridgeOperations    int    `json:"bridgeOperations"`
	BridgeProtocol      int    `json:"bridgeProtocol"`
	CompatibilitySchema int    `json:"compatibilitySchema"`
	RuntimeSchema       int    `json:"runtimeSchema"`
	RuntimeKind         string `json:"runtimeKind"`
	SourceSHA256        string `json:"sourceSha256"`
	ModuleSHA256        string `json:"moduleSha256"`
}

func FinalSeal(opts FinalSealOptions) error {
	root, err := repoRoot()
	if err != nil {
		return err
	}
	if opts.Jobs <= 0 {
		opts.Jobs = 2
	}
	if err = PurgeLegacyPythonResidue(root); err != nil {
		return err
	}
	if err = ValidateRepositoryPurity(root); err != nil {
		return err
	}
	if err = testseal.Validate(root, false); err != nil {
		return err
	}
	bundle, err := contracts.LoadDir(filepath.Join(root, "migration", "contracts", "v1"))
	if err != nil {
		return err
	}
	if err = bundle.Validate(); err != nil {
		return err
	}
	if !opts.SkipValidation {
		if err = Validate(); err != nil {
			return err
		}
	}
	work := opts.WorkDir
	cleanup := false
	if work == "" {
		work, err = os.MkdirTemp("", "chrootctl-go17-seal-*")
		if err != nil {
			return err
		}
		cleanup = true
	}
	if cleanup {
		defer os.RemoveAll(work)
	}
	if err = os.MkdirAll(work, 0755); err != nil {
		return err
	}
	srcA, err := BuildSource(SourceOptions{Version: "go17-seal", Output: filepath.Join(work, "source-a.tar.gz")})
	if err != nil {
		return err
	}
	srcB, err := BuildSource(SourceOptions{Version: "go17-seal", Output: filepath.Join(work, "source-b.tar.gz")})
	if err != nil {
		return err
	}
	shaA, err := shaFile(srcA)
	if err != nil {
		return err
	}
	shaB, err := shaFile(srcB)
	if err != nil {
		return err
	}
	if shaA != shaB {
		return fmt.Errorf("GO17 source archive is not deterministic: %s != %s", shaA, shaB)
	}
	runtime, err := BuildRuntime(RuntimeOptions{OutputRoot: filepath.Join(work, "runtime"), Jobs: opts.Jobs})
	if err != nil {
		return err
	}
	zipA := filepath.Join(work, "module-a.zip")
	zipB := filepath.Join(work, "module-b.zip")
	if _, err = BuildModule(ModuleOptions{OutputDir: filepath.Join(work, "module-a"), ZipPath: zipA, RuntimeDir: runtime, Jobs: opts.Jobs}); err != nil {
		return err
	}
	if _, err = BuildModule(ModuleOptions{OutputDir: filepath.Join(work, "module-b"), ZipPath: zipB, RuntimeDir: runtime, Jobs: opts.Jobs}); err != nil {
		return err
	}
	modA, err := shaFile(zipA)
	if err != nil {
		return err
	}
	modB, err := shaFile(zipB)
	if err != nil {
		return err
	}
	if modA != modB {
		return fmt.Errorf("GO17 module ZIP is not deterministic: %s != %s", modA, modB)
	}
	if err = chmodule.ValidateRendered(filepath.Join(work, "module-a")); err != nil {
		return err
	}
	summary := finalSealSummary{ContractSchema: contracts.ContractSchemaVersion, CommandNodes: bundle.CLI.CommandNodeCount, BridgeOperations: bundle.Bridge.OperationCount, BridgeProtocol: bundle.Bridge.ProtocolVersion, CompatibilitySchema: bundle.Release.CompatibilitySchemaVersion, RuntimeSchema: bundle.Release.NativeRuntime.SchemaVersion, RuntimeKind: bundle.Release.NativeRuntime.Kind, SourceSHA256: shaA, ModuleSHA256: modA}
	raw, _ := json.MarshalIndent(summary, "", "  ")
	fmt.Println(string(raw))
	return nil
}
