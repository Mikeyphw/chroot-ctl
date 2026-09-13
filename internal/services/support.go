package services

import (
	"archive/zip"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"chrootctl/internal/model"
	"chrootctl/internal/mutation"
	"chrootctl/internal/redaction"
)

type SupportService struct{ C *Container }

func (s *SupportService) ExportBundle(ctx context.Context, archive string, extra map[string]any) (model.SupportBundleResult, error) {
	if archive == "" {
		archive = ManagedArchive(fmt.Sprintf("chrootctl-support-%d", time.Now().Unix()), "zip")
	}
	managedRoot, err := EnsureManagedTransferRoot()
	if err != nil {
		return model.SupportBundleResult{}, err
	}
	archive, err = filepath.Abs(archive)
	if err != nil {
		return model.SupportBundleResult{}, err
	}
	archive, err = contained(managedRoot, archive, "support bundle artifact")
	if err != nil {
		return model.SupportBundleResult{}, err
	}
	if s.C.DryRun {
		included := []string{"chroots.json", "host-doctor.json", "lifecycle.json", "module-runtime.json"}
		if extra != nil {
			included = append(included, "extra.json")
		}
		if _, err := os.Stat(s.C.BaseConfig.LogFile); err == nil {
			included = append(included, "chrootctl.log")
		}
		return model.SupportBundleResult{Archive: archive, Included: included}, nil
	}
	if err := os.MkdirAll(filepath.Dir(archive), 0o700); err != nil {
		return model.SupportBundleResult{}, err
	}
	tmp, err := os.CreateTemp(filepath.Dir(archive), "."+filepath.Base(archive)+".partial-")
	if err != nil {
		return model.SupportBundleResult{}, err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	f := tmp
	zw := zip.NewWriter(f)
	included := []string{}
	addJSON := func(name string, v any) error {
		safe := redaction.Value(v)
		b, e := json.MarshalIndent(safe, "", "  ")
		if e != nil {
			return e
		}
		w, e := zw.Create(name)
		if e != nil {
			return e
		}
		_, e = w.Write(append(b, '\n'))
		if e == nil {
			included = append(included, name)
		}
		return e
	}
	rows, _ := s.C.Chroots().List(ctx)
	_ = addJSON("chroots.json", rows)
	_ = addJSON("host-doctor.json", s.C.System().HostDoctor(ctx))
	_ = addJSON("lifecycle.json", s.C.Lifecycle().Status())
	_ = addJSON("module-runtime.json", s.C.ModuleRuntime().Status())
	if extra != nil {
		_ = addJSON("extra.json", extra)
	}
	if b, e := os.ReadFile(s.C.BaseConfig.LogFile); e == nil {
		text := redaction.String(string(b))
		if len(text) > 256*1024 {
			text = text[len(text)-256*1024:]
		}
		w, _ := zw.Create("chrootctl.log")
		_, _ = w.Write([]byte(text))
		included = append(included, "chrootctl.log")
	}
	if e := zw.Close(); e != nil {
		f.Close()
		return model.SupportBundleResult{}, e
	}
	if e := f.Sync(); e != nil {
		f.Close()
		return model.SupportBundleResult{}, e
	}
	if e := f.Close(); e != nil {
		return model.SupportBundleResult{}, e
	}
	if e := os.Rename(tmpName, archive); e != nil {
		return model.SupportBundleResult{}, e
	}
	if e := mutation.SyncDir(filepath.Dir(archive)); e != nil {
		return model.SupportBundleResult{}, e
	}
	artifact, e := s.C.Transfer().RegisterArtifact(ctx, archive, "support-bundle", "", nil, map[string]any{"included": included})
	if e != nil {
		return model.SupportBundleResult{}, e
	}
	return model.SupportBundleResult{Archive: archive, Included: included, ArtifactID: artifact.ArtifactID}, nil
}
func sanitizeText(s string) string { return strings.TrimSpace(redaction.String(s)) }
