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
	WorkDir      string
	Jobs         int
	GO02Evidence string
	EvidencePath string
}

type finalSealSummary struct {
	ContractSchema      int    `json:"contractSchema"`
	CommandNodes        int    `json:"commandNodes"`
	BridgeOperations    int    `json:"bridgeOperations"`
	BridgeProtocol      int    `json:"bridgeProtocol"`
	CompatibilitySchema int    `json:"compatibilitySchema"`
	RuntimeSchema       int    `json:"runtimeSchema"`
	RuntimeKind         string `json:"runtimeKind"`
	GO02DeviceAccepted  bool   `json:"go02DeviceAccepted"`
	SourceSHA256        string `json:"sourceSha256"`
	ModuleSHA256        string `json:"moduleSha256"`
	EvidencePath        string `json:"evidencePath"`
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

	checks := map[string]validationCheck{}
	if err = recordCheck(checks, "repo_purity", "repoctl repository-purity", "internal-check", func() error {
		return ValidateRepositoryPurity(root)
	}); err != nil {
		return err
	}
	if err = recordCheck(checks, "audit_coverage", "repoctl audit-coverage + build-foundation", "internal-check", func() error {
		if e := ValidateAuditCoverage(root); e != nil {
			return e
		}
		if e := ValidateBuildFoundation(root); e != nil {
			return e
		}
		if e := ValidateConfigRegistryFoundation(root); e != nil {
			return e
		}
		if e := ValidatePrivilegeTrustBoundary(root); e != nil {
			return e
		}
		if e := ValidateProcessTransportBoundary(root); e != nil {
			return e
		}
		if e := ValidateMutationEngineGateA(root); e != nil {
			return e
		}
		if e := ValidateCRUDAtomicity(root); e != nil {
			return e
		}
		if e := ValidateMountServiceRuntime(root); e != nil {
			return e
		}
		if e := ValidateSnapshotFidelity(root); e != nil {
			return e
		}
		if e := ValidateTransferArtifactPlane(root); e != nil {
			return e
		}
		if e := ValidateInstallerUpgradeReconstruction(root); e != nil {
			return e
		}
		if e := ValidateUserIdentitySafety(root); e != nil {
			return e
		}
		if e := ValidateCatalogPackageWorkflow(root); e != nil {
			return e
		}
		if e := ValidateClipboardPrivilegedIntegration(root); e != nil {
			return e
		}
		if e := ValidateModuleRuntimeReleaseTrust(root); e != nil {
			return e
		}
		if e := ValidateLoggingDiagnosticsAuditEvidence(root); e != nil {
			return e
		}
		return ValidateBridgeProtocolV2Convergence(root)
	}); err != nil {
		return err
	}

	bundle, err := contracts.LoadDir(filepath.Join(root, "migration", "contracts", "v1"))
	if err != nil {
		return err
	}
	if err = recordCheck(checks, "go_contracts", "repoctl frozen/live contract seal", "internal-check", func() error {
		if e := testseal.Validate(root, false); e != nil {
			return e
		}
		if e := bundle.Validate(); e != nil {
			return e
		}
		return ValidateLiveContracts(root, bundle)
	}); err != nil {
		return err
	}

	if err = EnsureGO02DeviceAcceptance(root, opts.GO02Evidence); err != nil {
		return err
	}

	if err = recordCheck(checks, "go_test", "go test -p 2 ./...", "subprocess", func() error {
		return run(root, nil, "go", "test", "-p", "2", "./...")
	}); err != nil {
		return err
	}
	if err = recordCheck(checks, "go_vet", "go vet ./...", "subprocess", func() error {
		return run(root, nil, "go", "vet", "./...")
	}); err != nil {
		return err
	}

	androidRoot := filepath.Join(root, "android")
	androidCommand := "./gradlew --no-daemon --continue :chrootctlDebugValidation"
	if err = recordCheckGroup(
		checks,
		[]string{"android_compileDebugKotlin", "android_testDebugUnitTest", "android_lintDebug"},
		androidCommand,
		"subprocess",
		func() error {
			return run(androidRoot, nil, "./gradlew", "--no-daemon", "--continue", ":chrootctlDebugValidation")
		},
	); err != nil {
		return err
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

	var shaA string
	if err = recordCheck(checks, "source_package", "repoctl deterministic source package x2", "internal-check", func() error {
		srcA, e := BuildSource(SourceOptions{Version: "go17-seal", Output: filepath.Join(work, "source-a.tar.gz")})
		if e != nil {
			return e
		}
		srcB, e := BuildSource(SourceOptions{Version: "go17-seal", Output: filepath.Join(work, "source-b.tar.gz")})
		if e != nil {
			return e
		}
		shaA, e = shaFile(srcA)
		if e != nil {
			return e
		}
		shaB, e := shaFile(srcB)
		if e != nil {
			return e
		}
		if shaA != shaB {
			return fmt.Errorf("GO17 source archive is not deterministic: %s != %s", shaA, shaB)
		}
		return nil
	}); err != nil {
		return err
	}

	runtimeDir, err := BuildRuntime(RuntimeOptions{OutputRoot: filepath.Join(work, "runtime"), Jobs: opts.Jobs})
	if err != nil {
		return err
	}
	zipA, zipB := filepath.Join(work, "module-a.zip"), filepath.Join(work, "module-b.zip")
	if err = recordCheck(checks, "module_render", "repoctl build-module + ValidateRendered", "internal-check", func() error {
		if _, e := BuildModule(ModuleOptions{OutputDir: filepath.Join(work, "module-a"), ZipPath: zipA, RuntimeDir: runtimeDir, Jobs: opts.Jobs}); e != nil {
			return e
		}
		return chmodule.ValidateRendered(filepath.Join(work, "module-a"))
	}); err != nil {
		return err
	}

	var modA string
	if err = recordCheck(checks, "module_zip", "repoctl deterministic module ZIP x2", "internal-check", func() error {
		if _, e := BuildModule(ModuleOptions{OutputDir: filepath.Join(work, "module-b"), ZipPath: zipB, RuntimeDir: runtimeDir, Jobs: opts.Jobs}); e != nil {
			return e
		}
		var e error
		modA, e = shaFile(zipA)
		if e != nil {
			return e
		}
		modB, e := shaFile(zipB)
		if e != nil {
			return e
		}
		if modA != modB {
			return fmt.Errorf("GO17 module ZIP is not deterministic: %s != %s", modA, modB)
		}
		return nil
	}); err != nil {
		return err
	}

	if err = recordCheck(checks, "module_shell", "repoctl module shell contract", "internal-check", func() error {
		return validateModuleShellContract(filepath.Join(work, "module-a"))
	}); err != nil {
		return err
	}
	if err = recordCheck(checks, "source_no_webui", "repoctl retired WebUI regression scan", "internal-check", func() error {
		return validateNoWebUI(root)
	}); err != nil {
		return err
	}

	evidencePath, err := writeFinalSealEvidence(root, opts.EvidencePath, checks)
	if err != nil {
		return err
	}
	summary := finalSealSummary{
		ContractSchema: contracts.ContractSchemaVersion, CommandNodes: bundle.CLI.CommandNodeCount,
		BridgeOperations: bundle.Bridge.OperationCount, BridgeProtocol: bundle.Bridge.ProtocolVersion,
		CompatibilitySchema: bundle.Release.CompatibilitySchemaVersion, RuntimeSchema: bundle.Release.NativeRuntime.SchemaVersion,
		RuntimeKind: bundle.Release.NativeRuntime.Kind, GO02DeviceAccepted: true, SourceSHA256: shaA, ModuleSHA256: modA,
		EvidencePath: evidencePath,
	}
	raw, _ := json.MarshalIndent(summary, "", "  ")
	fmt.Println(string(raw))
	return nil
}
