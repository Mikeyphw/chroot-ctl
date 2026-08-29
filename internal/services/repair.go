package services

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"chrootctl/internal/model"
	"chrootctl/internal/registry"
	"chrootctl/internal/validation"
)

type RepairService struct{ C *Container }

func (s *RepairService) candidateDirs() ([]string, error) {
	root, err := filepath.Abs(s.C.BaseConfig.ChrootRoot)
	if err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(root)
	if os.IsNotExist(err) {
		return []string{}, nil
	}
	if err != nil {
		return nil, err
	}
	out := []string{}
	for _, e := range entries {
		if !e.IsDir() || e.Type()&os.ModeSymlink != 0 {
			continue
		}
		if _, err := validation.ChrootName(e.Name()); err != nil {
			continue
		}
		p := filepath.Join(root, e.Name())
		a, _ := filepath.Abs(p)
		if filepath.Dir(a) == root {
			out = append(out, a)
		}
	}
	sort.Strings(out)
	return out, nil
}
func (s *RepairService) PreviewItems(ctx context.Context) ([]map[string]any, error) {
	rows, err := s.C.Registry.List(ctx)
	if err != nil {
		return nil, err
	}
	by := map[string]registry.Chroot{}
	for _, r := range rows {
		by[r.Name] = r
	}
	dirs, err := s.candidateDirs()
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	out := []map[string]any{}
	for _, p := range dirs {
		name := filepath.Base(p)
		seen[name] = true
		r, ok := by[name]
		if !ok {
			out = append(out, map[string]any{"item_id": "chroot:" + name, "name": name, "kind": "missing-record", "severity": "warn", "action": "register", "path": p, "expected_path": "", "summary": "Filesystem path exists without a registry record: " + p, "impact": "Registers the existing directory so it shows up in the native dashboard again.", "diff_lines": []string{"- registry[" + name + "] = missing", "+ registry[" + name + "].path = " + p}})
			continue
		}
		rp, _ := filepath.Abs(r.Path)
		if rp != p {
			out = append(out, map[string]any{"item_id": "chroot:" + name, "name": name, "kind": "mismatched-path", "severity": "warn", "action": "fix-path", "path": p, "expected_path": rp, "summary": "Registry path does not match filesystem path for " + name, "impact": "Updates the registry path to the real directory.", "diff_lines": []string{"- registry[" + name + "].path = " + rp, "+ registry[" + name + "].path = " + p}})
		}
	}
	for _, r := range rows {
		if seen[r.Name] {
			continue
		}
		if _, e := os.Stat(r.Path); os.IsNotExist(e) {
			out = append(out, map[string]any{"item_id": "registry:" + r.Name, "name": r.Name, "kind": "missing-path", "severity": "bad", "action": "remove-record", "path": r.Path, "expected_path": r.Path, "summary": "Registry record points to a missing path: " + r.Path, "impact": "Removes a broken registry entry without deleting filesystem data.", "diff_lines": []string{"- registry[" + r.Name + "] = " + r.Path, "+ registry[<name>] removed"}})
		}
	}
	return out, nil
}
func (s *RepairService) PreviewPlan(ctx context.Context, decisions []map[string]string) (map[string]any, error) {
	items, err := s.PreviewItems(ctx)
	if err != nil {
		return nil, err
	}
	by := map[string]map[string]any{}
	for _, item := range items {
		by[fmt.Sprint(item["item_id"])] = item
	}
	selected := []map[string]any{}
	summary := map[string]any{"selected_count": 0, "register_count": 0, "fix_path_count": 0, "remove_record_count": 0, "skip_count": 0}
	for _, decision := range decisions {
		id := strings.TrimSpace(decision["item_id"])
		item, ok := by[id]
		if !ok {
			return nil, fmt.Errorf("repair decision is stale or unknown: %s", id)
		}
		action := strings.TrimSpace(decision["action"])
		if action == "skip" {
			summary["skip_count"] = summary["skip_count"].(int) + 1
			continue
		}
		kind := fmt.Sprint(item["kind"])
		allowed := map[string]string{"missing-record": "register", "mismatched-path": "fix-path", "missing-path": "remove-record"}[kind]
		if allowed == "" || action != allowed {
			return nil, fmt.Errorf("repair action %q is not valid for %q", action, kind)
		}
		summary["selected_count"] = summary["selected_count"].(int) + 1
		switch action {
		case "register":
			summary["register_count"] = summary["register_count"].(int) + 1
		case "fix-path":
			summary["fix_path_count"] = summary["fix_path_count"].(int) + 1
		case "remove-record":
			summary["remove_record_count"] = summary["remove_record_count"].(int) + 1
		}
		selected = append(selected, map[string]any{"item_id": id, "name": item["name"], "kind": kind, "severity": item["severity"], "action": action, "summary": item["summary"], "impact": item["impact"], "path": item["path"], "expected_path": item["expected_path"]})
	}
	warnings := []string{}
	if summary["remove_record_count"].(int) > 0 {
		warnings = append(warnings, "Removing registry records is destructive for UI metadata, but does not delete filesystem data.")
	}
	if summary["register_count"].(int) > 0 {
		warnings = append(warnings, "Recovered chroots may need distro/release metadata review after registration.")
	}
	if summary["fix_path_count"].(int) > 0 {
		warnings = append(warnings, "Re-run doctor or status after fixing paths to confirm runtime wiring.")
	}
	next := []string{"Select at least one repair action to continue."}
	if summary["selected_count"].(int) > 0 {
		next = []string{"Queue the repair job and review the result on the Jobs page."}
	}
	summary["warnings"] = warnings
	summary["next_steps"] = next
	return map[string]any{"summary": summary, "selected": selected, "ok": summary["selected_count"].(int) > 0}, nil
}
func (s *RepairService) ApplyPlan(ctx context.Context, decisions []map[string]string) (model.RegistryRepairResult, error) {
	items, err := s.PreviewItems(ctx)
	if err != nil {
		return model.RegistryRepairResult{}, err
	}
	by := map[string]map[string]any{}
	for _, i := range items {
		by[fmt.Sprint(i["item_id"])] = i
	}
	muts := []registry.ChrootMutation{}
	res := model.RegistryRepairResult{Preview: false, NextSteps: []string{"Run chrootctl doctor for repaired chroots."}}
	for _, d := range decisions {
		i, ok := by[d["item_id"]]
		if !ok {
			return res, fmt.Errorf("repair decision is stale or unknown: %s", d["item_id"])
		}
		action := d["action"]
		if action == "skip" {
			continue
		}
		name := fmt.Sprint(i["name"])
		kind := fmt.Sprint(i["kind"])
		allowed := map[string]string{"missing-record": "register", "mismatched-path": "fix-path", "missing-path": "remove-record"}[kind]
		if action != allowed {
			return res, fmt.Errorf("invalid repair action %q for %s", action, kind)
		}
		switch kind {
		case "missing-record":
			p := fmt.Sprint(i["path"])
			muts = append(muts, registry.ChrootMutation{Action: "upsert", Name: name, Distro: "unknown", Path: p, Phase: "registered", Metadata: map[string]any{"recovered": "yes", "repair_source": "filesystem-scan"}})
			res.MissingRecords = append(res.MissingRecords, name)
			res.RepairedRecords = append(res.RepairedRecords, name)
		case "mismatched-path":
			r, e := s.C.Registry.Get(ctx, name)
			if e != nil || r == nil {
				return res, fmt.Errorf("registry record disappeared after preview: %s", name)
			}
			muts = append(muts, registry.ChrootMutation{Action: "upsert", Name: name, Distro: r.Distro, Path: fmt.Sprint(i["path"]), Arch: r.Arch, ReleaseName: r.ReleaseName, Version: r.Version, Phase: r.Phase, Installed: r.Installed, Metadata: r.Metadata})
			res.MismatchedPaths = append(res.MismatchedPaths, name)
			res.RepairedRecords = append(res.RepairedRecords, name)
		case "missing-path":
			muts = append(muts, registry.ChrootMutation{Action: "delete", Name: name})
			res.MissingPaths = append(res.MissingPaths, name)
			res.RemovedRecords = append(res.RemovedRecords, name)
		}
	}
	if err := s.C.Registry.ApplyChrootMutations(ctx, muts); err != nil {
		return res, err
	}
	dirs, _ := s.candidateDirs()
	res.ScannedPaths = len(dirs)
	return res, nil
}
func strPtr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
func (s *RepairService) PreviewRegistryRepair(ctx context.Context) (model.RegistryRepairResult, error) {
	items, e := s.PreviewItems(ctx)
	if e != nil {
		return model.RegistryRepairResult{}, e
	}
	r := model.RegistryRepairResult{Preview: true, NextSteps: []string{"Review the repair candidates before applying changes."}}
	for _, i := range items {
		switch i["kind"] {
		case "missing-record":
			r.MissingRecords = append(r.MissingRecords, fmt.Sprint(i["name"]))
		case "mismatched-path":
			r.MismatchedPaths = append(r.MismatchedPaths, fmt.Sprint(i["name"]))
		case "missing-path":
			r.MissingPaths = append(r.MissingPaths, fmt.Sprint(i["name"]))
		}
	}
	dirs, _ := s.candidateDirs()
	r.ScannedPaths = len(dirs)
	return r, nil
}
