package services

import (
	"strings"
	"testing"
)

func TestImportStoragePlanChoosesStreamingWhenStagedWouldDoubleExpandedSpace(t *testing.T) {
	gib := uint64(1024 * 1024 * 1024)
	plan := importStoragePlan{
		Target:                          filesystemCapacity{Anchor: "/data", FreeBytes: 40 * gib, Device: 1},
		Temp:                            filesystemCapacity{Anchor: "/data/local/tmp", FreeBytes: 40 * gib, Device: 1},
		SameFilesystem:                  true,
		StreamingEstimatedRequired:      26 * gib,
		StagedCombinedEstimatedRequired: 46 * gib,
	}
	if got := plan.autoStrategy(); got != "streaming" {
		t.Fatalf("strategy=%q want streaming", got)
	}
}

func TestImportStoragePlanChoosesStagedWhenCombinedCapacityIsComfortable(t *testing.T) {
	gib := uint64(1024 * 1024 * 1024)
	plan := importStoragePlan{
		Target:                          filesystemCapacity{Anchor: "/data", FreeBytes: 100 * gib, Device: 1},
		Temp:                            filesystemCapacity{Anchor: "/data/local/tmp", FreeBytes: 100 * gib, Device: 1},
		SameFilesystem:                  true,
		StreamingEstimatedRequired:      26 * gib,
		StagedCombinedEstimatedRequired: 46 * gib,
	}
	if got := plan.autoStrategy(); got != "staged" {
		t.Fatalf("strategy=%q want staged", got)
	}
}

func TestExplicitStagedSpaceFailureIsActionable(t *testing.T) {
	plan := importStoragePlan{
		Target:                          filesystemCapacity{Anchor: "/data", FreeBytes: 10, Device: 1},
		Temp:                            filesystemCapacity{Anchor: "/data/local/tmp", FreeBytes: 10, Device: 1},
		SameFilesystem:                  true,
		StagedCombinedEstimatedRequired: 20,
	}
	err := plan.stagedSpaceError()
	if err == nil || !strings.Contains(err.Error(), "INSUFFICIENT_IMPORT_SPACE") || !strings.Contains(err.Error(), "--import-strategy=streaming") {
		t.Fatalf("unexpected staged space error: %v", err)
	}
}

func TestImportEstimateIsBoundedByArchiveSafetyLimit(t *testing.T) {
	got := estimateImportExpandedBytes(uint64(maxArchiveExpandedBytes))
	if got != uint64(maxArchiveExpandedBytes) {
		t.Fatalf("estimate=%d want %d", got, maxArchiveExpandedBytes)
	}
	if importSafetyReserve(1) < importStorageMinimumReserve {
		t.Fatal("safety reserve fell below minimum")
	}
}
