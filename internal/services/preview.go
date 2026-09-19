package services

import (
	"context"
	"fmt"

	"chrootctl/internal/model"
)

// PreviewService exposes deterministic, side-effect-free plans used by the CLI
// and Android bridge before an operation is queued.
type PreviewService struct{ C *Container }

func (s *PreviewService) Install(ctx context.Context, request model.InstallRequest) (map[string]any, error) {
	return s.C.Install().PreviewInstall(request), nil
}
func (s *PreviewService) Export(ctx context.Context, name, archive string) (map[string]any, error) {
	return s.C.Chroots().ExportPreview(ctx, name, archive)
}
func (s *PreviewService) Import(ctx context.Context, archive, name, conflict, password string, allowLegacyMetadata bool) (map[string]any, error) {
	// Preview always permits reading a legacy manifest so the caller can receive
	// an actionable blocking reason and explicitly opt in. The actual import
	// still fails closed unless allowLegacyMetadata is carried into execution.
	inspection, err := s.C.Transfer().InspectWithControl(ctx, archive, password, TransferControl{AllowLegacyMetadata: true})
	if err != nil {
		return nil, err
	}
	if name != "" {
		inspection.SuggestedName = name
	}
	if conflict == "" {
		conflict = "rename"
	}
	blocking := []map[string]string{}
	warnings := []string{}
	if conflict != "rename" && conflict != "overwrite" {
		blocking = append(blocking, map[string]string{"code": "invalid_conflict", "message": "Conflict strategy must be rename or overwrite."})
	}
	if inspection.Metadata["metadata_fidelity"] == "legacy_unverified" {
		message := "This archive predates the CHR09 rootfs metadata contract. Ownership, special bits, ACL/xattr/capability, device-node, sparse-file, and related metadata fidelity cannot be proven from the archive manifest."
		if allowLegacyMetadata {
			warnings = append(warnings, message+" Import is allowed only because legacy compatibility was explicitly enabled; the imported chroot will be permanently marked metadata_fidelity=legacy_unverified.")
		} else {
			blocking = append(blocking, map[string]string{"code": "legacy_metadata_unverified", "message": message + " Explicitly enable legacy metadata compatibility to continue."})
		}
	}
	return map[string]any{
		"ok": len(blocking) == 0, "kind": "import", "archive": archive,
		"inspection": inspection, "conflict": conflict, "blocking": blocking,
		"warnings": warnings, "allowLegacyMetadata": allowLegacyMetadata,
	}, nil
}
func (s *PreviewService) Delete(ctx context.Context, name string) (map[string]any, error) {
	return s.C.Chroots().DeletePreview(ctx, name)
}
func (s *PreviewService) Upgrade(ctx context.Context, name string) (map[string]any, error) {
	r, err := s.C.Registry.Get(ctx, name)
	if err != nil {
		return nil, err
	}
	if r == nil {
		return nil, fmt.Errorf("unknown chroot: %s", name)
	}
	blocking := []map[string]string{}
	if r.Path == "" {
		blocking = append(blocking, map[string]string{"code": "missing_path", "message": "No chroot path is registered."})
	}
	if !r.Installed || r.Phase != "finalize" {
		blocking = append(blocking, map[string]string{"code": "not_finalized", "message": fmt.Sprintf("Upgrade requires an installed finalized chroot; current phase=%s installed=%v.", r.Phase, r.Installed)})
	}
	if r.Distro != "ubuntu" && r.Distro != "arch" {
		blocking = append(blocking, map[string]string{"code": "unsupported_distro", "message": "Upgrade does not support registered distro: " + r.Distro})
	}
	if _, err := s.C.ResolveTarget(ctx, name, true); err != nil {
		blocking = append(blocking, map[string]string{"code": "target_identity", "message": err.Error()})
	}
	warnings := []string{}
	if s.C.BaseConfig.SnapshotBeforeDestructive {
		warnings = append(warnings, "A managed pre-upgrade snapshot will be created before package commands run.")
	}
	return map[string]any{
		"ok": len(blocking) == 0, "kind": "upgrade", "name": name, "distro": r.Distro,
		"phase": r.Phase, "installed": r.Installed,
		"message":  map[bool]string{true: "Upgrade preview is ready.", false: "Upgrade preview has blocking issues."}[len(blocking) == 0],
		"dry_run":  map[string]any{"supported": true, "command": fmt.Sprintf("chrootctl --name %s upgrade --dry-run", name)},
		"warnings": warnings, "blocking": blocking,
	}, nil
}
