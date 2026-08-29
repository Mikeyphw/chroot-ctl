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
func (s *PreviewService) Import(ctx context.Context, archive, name, conflict, password string) (map[string]any, error) {
	inspection, err := s.C.Transfer().Inspect(ctx, archive, password)
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
	if conflict != "rename" && conflict != "overwrite" {
		blocking = append(blocking, map[string]string{"code": "invalid_conflict", "message": "Conflict strategy must be rename or overwrite."})
	}
	return map[string]any{
		"ok": len(blocking) == 0, "kind": "import", "archive": archive,
		"inspection": inspection, "conflict": conflict, "blocking": blocking,
		"warnings": []string{},
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
	warnings := []string{}
	if !r.Installed {
		warnings = append(warnings, "Chroot is not marked fully installed yet.")
	}
	return map[string]any{
		"ok": len(blocking) == 0, "kind": "upgrade", "name": name, "distro": r.Distro,
		"phase": r.Phase, "installed": r.Installed,
		"message":  map[bool]string{true: "Upgrade preview is ready.", false: "Upgrade preview has blocking issues."}[len(blocking) == 0],
		"dry_run":  map[string]any{"supported": true, "command": fmt.Sprintf("chrootctl --name %s upgrade --dry-run", name)},
		"warnings": warnings, "blocking": blocking,
	}, nil
}
