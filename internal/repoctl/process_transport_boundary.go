package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateProcessTransportBoundary is the executable CHR05 seal. It keeps
// process cancellation, bounded capture and Android privileged transport from
// regressing back to direct-process-only termination or synchronous large Binder I/O.
func ValidateProcessTransportBoundary(root string) error {
	read := func(rel string) (string, error) {
		raw, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", err
		}
		return string(raw), nil
	}
	require := func(rel string, tokens ...string) error {
		body, err := read(rel)
		if err != nil {
			return fmt.Errorf("CHR05 read %s: %w", rel, err)
		}
		for _, token := range tokens {
			if !strings.Contains(body, token) {
				return fmt.Errorf("CHR05 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	forbid := func(rel string, tokens ...string) error {
		body, err := read(rel)
		if err != nil {
			return fmt.Errorf("CHR05 read %s: %w", rel, err)
		}
		for _, token := range tokens {
			if strings.Contains(body, token) {
				return fmt.Errorf("CHR05 %s retains forbidden transport/process token %q", rel, token)
			}
		}
		return nil
	}

	if err := require("internal/system/system.go", "OutputPolicy", "boundedCaptureWriter", "processGroupAlive", "TerminateProcessIdentity", "command timed out after", "command cancelled"); err != nil {
		return err
	}
	if err := require("internal/services/transfer.go", "TransferControl", "ImportWithControl", "ExportWithControl", "copyWithControl", "control.check(ctx)"); err != nil {
		return err
	}
	if err := require("internal/services/units.go", "Timeout: 30 * time.Second"); err != nil {
		return err
	}
	if err := require("cmd/chrootctl/main.go", "context.WithCancelCause", "signal.Notify", "syscall.SIGINT", "syscall.SIGTERM"); err != nil {
		return err
	}

	client := "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RootServiceClient.kt"
	if err := require(client, "transferState(requestId)", "cancelTransfer(requestId)", "MAX_BINDER_REQUEST_BYTES", "TRANSFER_STALL_TIMEOUT_MS", "CALL_TIMEOUT_MS = 60_000L", "awaitTransfer", "invokeOnCompletion", "requireResponseRequestId"); err != nil {
		return err
	}
	if err := forbid(client, "callMutex", "TRANSFER_TIMEOUT_MS", "TRANSFER_CALL_WATCHDOG_MS"); err != nil {
		return err
	}

	service := "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt"
	if err := require(service, "ThreadPoolExecutor", "ArrayBlockingQueue", "MAX_BINDER_REQUEST_BYTES", "persistTransferState", "validateTransferPayload", "activeTransfers", "cancelTransfer", "handle.descriptor.close()", "ensurePrivateRootDirectory", "Os.chmod(directory.path, mode)", "ParcelFileDescriptor.dup", "AutoCloseOutputStream(owned).use"); err != nil {
		return err
	}
	if err := forbid(service, "Executors.newCachedThreadPool", "source.copyTo(destination)"); err != nil {
		return err
	}

	aidl := "android/app/src/main/aidl/com/mikeyphw/chrootctl/root/IChrootRootService.aidl"
	if err := require(aidl, "transferState(String requestId)", "cancelTransfer(String requestId)"); err != nil {
		return err
	}

	process := "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt"
	if err := require(process, "collectProcessTree", "Os.kill", "SIGTERM", "SIGKILL", "finally", "BridgeStreamResult"); err != nil {
		return err
	}

	validator := "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeOutputValidator.kt"
	if err := require(validator, "BRIDGE_RESPONSE_TRUNCATED", "BRIDGE_REQUEST_ID_MISMATCH", "expectedRequestId"); err != nil {
		return err
	}

	resolver := "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/RuntimeResolver.kt"
	if err := require(resolver, "CachedRuntime", "runtimeGeneration", "fileIdentity", "validateAndroidArm64Elf", "EM_AARCH64", "PROBE_TIMEOUT_SECONDS = 10L"); err != nil {
		return err
	}

	viewModel := "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt"
	if err := forbid(viewModel, "repository.close()"); err != nil {
		return err
	}

	operationService := "android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/ChrootOperationService.kt"
	if err := require(operationService, "resumePersistedOperation(null)", "reconcileUntilTerminal(operationId, repository)"); err != nil {
		return err
	}
	return nil
}
