package repoctl

import "testing"

func TestCHR23ValidateRoadmapConvergenceSeal(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateRoadmapConvergenceSeal(root); err != nil {
		t.Fatal(err)
	}
}

func TestCHR23EveryRoadmapSourceGatePassesTogether(t *testing.T) {
	root, err := repoRoot()
	if err != nil {
		t.Fatal(err)
	}
	gates := []struct {
		name string
		run  func(string) error
	}{
		{"audit-coverage", ValidateAuditCoverage},
		{"CHR01-build-foundation", ValidateBuildFoundation},
		{"CHR02-cli-contract", ValidateCLIContractFoundation},
		{"CHR03-config-registry", ValidateConfigRegistryFoundation},
		{"CHR04-privilege-trust", ValidatePrivilegeTrustBoundary},
		{"CHR05-process-transport", ValidateProcessTransportBoundary},
		{"CHR06-mutation-engine", ValidateMutationEngineGateA},
		{"CHR07-crud-atomicity", ValidateCRUDAtomicity},
		{"CHR08-mount-service-runtime", ValidateMountServiceRuntime},
		{"CHR09-snapshot-fidelity", ValidateSnapshotFidelity},
		{"CHR10-transfer-artifact", ValidateTransferArtifactPlane},
		{"CHR11-installer-upgrade", ValidateInstallerUpgradeReconstruction},
		{"CHR12-user-identity", ValidateUserIdentitySafety},
		{"CHR13-catalog-package", ValidateCatalogPackageWorkflow},
		{"CHR14-clipboard", ValidateClipboardPrivilegedIntegration},
		{"CHR15-module-runtime-release", ValidateModuleRuntimeReleaseTrust},
		{"CHR16-logging-diagnostics-audit", ValidateLoggingDiagnosticsAuditEvidence},
		{"CHR17-bridge-v2", ValidateBridgeProtocolV2Convergence},
		{"CHR18-android-operation-room", ValidateAndroidOperationRoomRecovery},
		{"CHR19-android-product-workspace", ValidateAndroidProductWorkspaceCorrectness},
		{"CHR20-navigation-final-release", ValidateNavigationAdaptiveFinalReleaseSeal},
	}
	for _, gate := range gates {
		t.Run(gate.name, func(t *testing.T) {
			if err := gate.run(root); err != nil {
				t.Fatal(err)
			}
		})
	}
}
