package services

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
)

const importStorageMinimumReserve = uint64(2 * 1024 * 1024 * 1024)

type filesystemCapacity struct {
	Anchor    string
	FreeBytes uint64
	Device    uint64
}

type importStoragePlan struct {
	Strategy                        string
	SourceBytes                     uint64
	EstimatedExpandedBytes          uint64
	EstimatedTarBytes               uint64
	SafetyReserveBytes              uint64
	Target                          filesystemCapacity
	Temp                            filesystemCapacity
	SameFilesystem                  bool
	StreamingEstimatedRequired      uint64
	StagedTargetEstimatedRequired   uint64
	StagedTempEstimatedRequired     uint64
	StagedCombinedEstimatedRequired uint64
	RemoteSourceMustBeStaged        bool
}

func filesystemCapacityFor(path string) (filesystemCapacity, error) {
	anchor := existingFilesystemAnchor(path)
	var fs syscall.Statfs_t
	if err := syscall.Statfs(anchor, &fs); err != nil {
		return filesystemCapacity{}, err
	}
	st, err := os.Stat(anchor)
	if err != nil {
		return filesystemCapacity{}, err
	}
	raw, ok := st.Sys().(*syscall.Stat_t)
	if !ok {
		return filesystemCapacity{}, fmt.Errorf("filesystem identity unavailable for %s", anchor)
	}
	return filesystemCapacity{Anchor: anchor, FreeBytes: uint64(fs.Bavail) * uint64(fs.Bsize), Device: uint64(raw.Dev)}, nil
}

func importSafetyReserve(expanded uint64) uint64 {
	reserve := expanded / 10
	if reserve < importStorageMinimumReserve {
		reserve = importStorageMinimumReserve
	}
	return reserve
}

func estimateImportExpandedBytes(sourceBytes uint64) uint64 {
	if sourceBytes == 0 {
		return uint64(maxArchiveExpandedBytes)
	}
	estimate := sourceBytes * 8
	limit := uint64(maxArchiveExpandedBytes)
	if estimate > limit || estimate < sourceBytes {
		return limit
	}
	return estimate
}

func buildImportStoragePlan(sourceBytes int64, tempDir, targetRoot string, remoteStaged bool) (importStoragePlan, error) {
	target, err := filesystemCapacityFor(targetRoot)
	if err != nil {
		return importStoragePlan{}, fmt.Errorf("inspect target filesystem capacity: %w", err)
	}
	temp, err := filesystemCapacityFor(tempDir)
	if err != nil {
		return importStoragePlan{}, fmt.Errorf("inspect temporary filesystem capacity: %w", err)
	}
	source := uint64(max64(sourceBytes, 0))
	expanded := estimateImportExpandedBytes(source)
	reserve := importSafetyReserve(expanded)
	tarEstimate := expanded
	plan := importStoragePlan{
		SourceBytes: source, EstimatedExpandedBytes: expanded, EstimatedTarBytes: tarEstimate,
		SafetyReserveBytes: reserve, Target: target, Temp: temp,
		SameFilesystem: target.Device == temp.Device, RemoteSourceMustBeStaged: remoteStaged,
	}
	plan.StreamingEstimatedRequired = expanded + reserve
	plan.StagedTargetEstimatedRequired = expanded + reserve
	plan.StagedTempEstimatedRequired = tarEstimate + reserve
	if remoteStaged {
		plan.StagedTempEstimatedRequired += source
	}
	plan.StagedCombinedEstimatedRequired = expanded + tarEstimate + reserve
	if remoteStaged {
		plan.StagedCombinedEstimatedRequired += source
	}
	return plan, nil
}

func (p importStoragePlan) stagedLikelyFits() bool {
	if p.SameFilesystem {
		return p.Target.FreeBytes >= p.StagedCombinedEstimatedRequired
	}
	return p.Target.FreeBytes >= p.StagedTargetEstimatedRequired && p.Temp.FreeBytes >= p.StagedTempEstimatedRequired
}

func (p importStoragePlan) autoStrategy() string {
	if p.stagedLikelyFits() {
		return "staged"
	}
	return "streaming"
}

func (p importStoragePlan) details(strategy string) map[string]any {
	return map[string]any{
		"strategy":                                 strategy,
		"source_bytes":                             p.SourceBytes,
		"estimated_expanded_bytes":                 p.EstimatedExpandedBytes,
		"estimated_tar_bytes":                      p.EstimatedTarBytes,
		"safety_reserve_bytes":                     p.SafetyReserveBytes,
		"target_filesystem":                        p.Target.Anchor,
		"target_free_bytes":                        p.Target.FreeBytes,
		"temp_filesystem":                          p.Temp.Anchor,
		"temp_free_bytes":                          p.Temp.FreeBytes,
		"same_filesystem":                          p.SameFilesystem,
		"streaming_estimated_required_bytes":       p.StreamingEstimatedRequired,
		"staged_target_estimated_required_bytes":   p.StagedTargetEstimatedRequired,
		"staged_temp_estimated_required_bytes":     p.StagedTempEstimatedRequired,
		"staged_combined_estimated_required_bytes": p.StagedCombinedEstimatedRequired,
	}
}

func exactImportSpaceError(root string, free, expanded, reserve, required uint64) error {
	return fmt.Errorf(
		"INSUFFICIENT_IMPORT_SPACE: target=%s free=%d expanded=%d safety_reserve=%d required=%d; choose streaming import when possible, free space, or move the chroot root to a filesystem with more capacity",
		filepath.Clean(existingFilesystemAnchor(root)), free, expanded, reserve, required,
	)
}

func (p importStoragePlan) stagedSpaceError() error {
	if p.stagedLikelyFits() {
		return nil
	}
	if p.SameFilesystem {
		return fmt.Errorf(
			"INSUFFICIENT_IMPORT_SPACE: staged strategy needs an estimated %d bytes on %s but only %d bytes are free; use --import-strategy=streaming or free space",
			p.StagedCombinedEstimatedRequired, p.Target.Anchor, p.Target.FreeBytes,
		)
	}
	return fmt.Errorf(
		"INSUFFICIENT_IMPORT_SPACE: staged strategy needs target=%d bytes on %s (free=%d) and temp=%d bytes on %s (free=%d); use --import-strategy=streaming or free space",
		p.StagedTargetEstimatedRequired, p.Target.Anchor, p.Target.FreeBytes,
		p.StagedTempEstimatedRequired, p.Temp.Anchor, p.Temp.FreeBytes,
	)
}
