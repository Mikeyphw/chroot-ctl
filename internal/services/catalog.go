package services

import (
	"chrootctl/internal/catalog"
	"chrootctl/internal/model"
	"chrootctl/internal/mutation"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	"context"
	"fmt"
)

type CatalogService struct {
	C          *Container
	Kind, Name string
}

func (s *CatalogService) cat() (catalog.Catalog, error) {
	cfg, e := s.C.ConfigFor(s.Name, "")
	if e != nil {
		return catalog.Catalog{}, e
	}
	kind := s.Kind
	if kind == "tools" {
		kind = "tool"
	}
	if kind == "addons" {
		kind = "addon"
	}
	if kind != "tool" && kind != "addon" {
		return catalog.Catalog{}, fmt.Errorf("unsupported catalog kind: %s", s.Kind)
	}
	return catalog.Catalog{Kind: kind, Config: &cfg}, nil
}
func (s *CatalogService) ListEntries(distro, category string) ([]catalog.Entry, error) {
	c, e := s.cat()
	if e != nil {
		return nil, e
	}
	return c.List(distro, category)
}
func (s *CatalogService) Categories(distro string) ([]string, error) {
	c, e := s.cat()
	if e != nil {
		return nil, e
	}
	return c.Categories(distro)
}
func (s *CatalogService) GetEntry(name string) (catalog.Entry, error) {
	c, e := s.cat()
	if e != nil {
		return catalog.Entry{}, e
	}
	return c.Get(name)
}

func (s *CatalogService) EnrichEntries(ctx context.Context, entries []catalog.Entry) []catalog.Entry {
	if s.Name == "" || len(entries) == 0 || s.C == nil || s.C.Registry == nil {
		return entries
	}
	rec, err := s.C.Registry.Get(ctx, s.Name)
	if err != nil || rec == nil {
		return entries
	}
	out := make([]catalog.Entry, 0, len(entries))
	for _, entry := range entries {
		out = append(out, entry.WithMetadataState(rec.Metadata))
	}
	return out
}

func (s *CatalogService) EntryState(ctx context.Context, name string) (catalog.Entry, error) {
	entry, err := s.GetEntry(name)
	if err != nil {
		return catalog.Entry{}, err
	}
	entries := s.EnrichEntries(ctx, []catalog.Entry{entry})
	if len(entries) == 1 {
		return entries[0], nil
	}
	return entry, nil
}
func (s *CatalogService) Preflight(ctx context.Context, entry catalog.Entry) ([]string, error) {
	rt, e := s.C.RuntimeFor(s.Name, "")
	if e != nil {
		return nil, e
	}
	if rt.Config.TargetArch != "" && rt.Config.TargetArch != sys.HostArch() && !sys.CanExecuteForeignArch(rt.Config.TargetArch) {
		return nil, fmt.Errorf("target %s architecture %s is not executable on host %s; configure qemu/binfmt first", s.Name, rt.Config.TargetArch, sys.HostArch())
	}
	if e = rt.Controller.Prepare(ctx, false); e != nil {
		return nil, fmt.Errorf("prepare catalog target: %w", e)
	}
	required := append([]string(nil), entry.Requires...)
	missing := []string{}
	for _, cmd := range uniqueStrings(required) {
		r, e := rt.Runner.Run(ctx, []string{"busybox", "chroot", rt.Config.ChrootBase(), "/bin/bash", "-lc", "command -v " + cmd + " >/dev/null 2>&1"}, sys.RunOptions{AllowFailure: true, ChrootEnv: true})
		if e != nil || r.ReturnCode != 0 {
			missing = append(missing, cmd)
		}
	}
	return missing, nil
}
func (s *CatalogService) Apply(ctx context.Context, names []string, progress func(any) error) ([]model.CatalogApplyResult, error) {
	rt, e := s.C.RuntimeFor(s.Name, "")
	if e != nil {
		return nil, e
	}
	c, e := s.cat()
	if e != nil {
		return nil, e
	}
	out := []model.CatalogApplyResult{}
	for _, name := range uniqueStrings(names) {
		entry, getErr := s.EntryState(ctx, name)
		if getErr != nil {
			return out, getErr
		}
		if entry.IsBlocked() {
			return out, fmt.Errorf("%s '%s' is blocked: %s", s.Kind, name, entry.StateReason)
		}
		if progress != nil {
			if e = progress(map[string]any{"phase": "catalog", "message": "Applying " + s.Kind + ": " + name, "kind": s.Kind, "name": name, "risk_level": entry.RiskLevel, "requires_confirmation": entry.RequiresConfirmation, "script_sha256": entry.ScriptSHA256}); e != nil {
				return out, e
			}
		}
		if s.C.DryRun {
			r, applyErr := c.Apply(ctx, name, rt.Config, rt.Runner, s.C.Registry)
			if applyErr != nil {
				return out, applyErr
			}
			out = append(out, r)
			continue
		}
		tx, beginErr := s.C.Mutations.Begin(ctx, mutation.Spec{Kind: "catalog.apply", Target: s.Name, Scope: "target", Detail: map[string]any{"catalog_kind": s.Kind, "entry": name}})
		if beginErr != nil {
			return out, beginErr
		}
		if beginErr = tx.Transition(ctx, registry.FSMutationPromoting, map[string]any{"catalog_kind": s.Kind, "entry": name}); beginErr != nil {
			return out, beginErr
		}
		r, applyErr := c.Apply(ctx, name, rt.Config, rt.Runner, s.C.Registry)
		if applyErr != nil {
			return out, tx.Fail(ctx, applyErr, map[string]any{"catalog_kind": s.Kind, "entry": name})
		}
		if beginErr = tx.Transition(context.WithoutCancel(ctx), registry.FSMutationCommitted, map[string]any{"catalog_kind": s.Kind, "entry": name}); beginErr != nil {
			return out, fmt.Errorf("catalog apply committed but mutation journal commit failed: %w", beginErr)
		}
		if beginErr = tx.Complete(ctx, map[string]any{"catalog_kind": s.Kind, "entry": name}); beginErr != nil {
			return out, fmt.Errorf("catalog apply committed but terminal journal persistence failed: %w", beginErr)
		}
		if auditErr := s.C.Audit().RecordMutation(context.WithoutCancel(ctx), "catalog.apply", s.Name+":"+s.Kind+":"+name, nil, map[string]string{"catalog_kind": s.Kind, "entry": name}); auditErr != nil {
			return out, auditErr
		}
		out = append(out, r)
	}
	return out, nil
}
