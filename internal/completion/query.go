package completion

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"chrootctl/internal/catalog"
	"chrootctl/internal/config"
	"chrootctl/internal/registry"
	"chrootctl/internal/validation"
)

// QueryOptions describes one dynamic shell-completion lookup. Completion is a
// strict read-only surface: it must never run runtime-layout migration, create a
// registry, configure logging, create operation state, or invoke root helpers.
type QueryOptions struct {
	ConfigPath string
	Name       string
	Topic      string
	Values     []string
}

func Query(ctx context.Context, options QueryOptions, out io.Writer) error {
	cfg, err := completionConfig(options.ConfigPath)
	if err != nil {
		return err
	}
	topic := options.Topic
	vals := options.Values
	switch topic {
	case "chroots", "installed-chroots", "chroot-details", "chroot-preview":
		rows := completionChroots(ctx, cfg)
		if topic == "chroot-details" {
			_, err = io.WriteString(out, ChrootDetails(rows))
			return err
		}
		if topic == "chroot-preview" {
			if len(vals) == 0 {
				return nil
			}
			for _, row := range rows {
				if row.Name == vals[0] {
					_, err = fmt.Fprintf(out, "name: %s\ndistro: %s\nphase: %s\npath: %s\ninstalled: %v\n", row.Name, row.Distro, row.Phase, row.Path, row.Installed)
					return err
				}
			}
			return nil
		}
		_, err = io.WriteString(out, ChrootNames(rows, topic == "installed-chroots"))
		return err
	case "users":
		name := strings.TrimSpace(options.Name)
		if name == "" && len(vals) > 0 {
			name = strings.TrimSpace(vals[0])
		}
		if name == "" {
			rows := completionChroots(ctx, cfg)
			installed := make([]string, 0, len(rows))
			for _, row := range rows {
				if row.Installed {
					installed = append(installed, row.Name)
				}
			}
			if len(installed) != 1 {
				return nil
			}
			name = installed[0]
		}
		root, err := completionTargetRoot(ctx, cfg, name)
		if err != nil || root == "" {
			return nil
		}
		data, err := os.ReadFile(filepath.Join(root, "etc", "passwd"))
		if err != nil {
			// Permission-restricted state simply yields no dynamic user names. The
			// completion path remains non-root and side-effect free.
			return nil
		}
		names := make([]string, 0)
		for _, line := range strings.Split(string(data), "\n") {
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			fields := strings.Split(line, ":")
			if len(fields) >= 7 {
				if name, e := validation.Username(fields[0]); e == nil {
					names = append(names, name)
				}
			}
		}
		sort.Strings(names)
		_, err = io.WriteString(out, strings.Join(names, "\n"))
		return err
	case "tools", "addons", "tool-categories", "addon-categories", "tool-details", "addon-details", "tool-preview", "addon-preview":
		return completionCatalog(cfg, topic, vals, out)
	default:
		return nil
	}
}

func completionConfig(path string) (config.ChrootConfig, error) {
	cfg, err := config.LoadReadOnly(path)
	if err == nil {
		return cfg, nil
	}
	// Default Android state can be intentionally root-only. Falling back to the
	// compiled defaults lets completion still discover public rootfs/catalog data
	// without escalating or mutating anything. Explicit user configuration errors
	// remain visible to direct __complete callers.
	if path == "" && (errors.Is(err, os.ErrPermission) || os.IsPermission(err)) {
		return config.Default(config.DetectRuntime()), nil
	}
	return config.ChrootConfig{}, err
}

func completionChroots(ctx context.Context, cfg config.ChrootConfig) []registry.Chroot {
	if reg, err := registry.OpenReadOnly(cfg.DatabasePath); err == nil {
		defer reg.Close()
		if rows, err := reg.List(ctx); err == nil {
			return rows
		}
	}
	// Registry state may be root-only. A conservative filesystem projection is
	// safe for completion because returned names are suggestions only and every
	// real command re-resolves the authoritative registry identity.
	entries, err := os.ReadDir(cfg.ChrootRoot)
	if err != nil {
		return nil
	}
	rows := make([]registry.Chroot, 0, len(entries))
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		name, err := validation.ChrootName(entry.Name())
		if err != nil || strings.HasPrefix(name, ".") {
			continue
		}
		root := filepath.Join(cfg.ChrootRoot, name)
		installed := exists(filepath.Join(root, "etc", "os-release")) || exists(filepath.Join(root, "bin", "sh"))
		rows = append(rows, registry.Chroot{Name: name, Distro: name, Path: root, Phase: "filesystem", Installed: installed})
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].Name < rows[j].Name })
	return rows
}

func completionTargetRoot(ctx context.Context, cfg config.ChrootConfig, rawName string) (string, error) {
	name, err := validation.ChrootName(rawName)
	if err != nil {
		return "", err
	}
	if reg, openErr := registry.OpenReadOnly(cfg.DatabasePath); openErr == nil {
		defer reg.Close()
		row, getErr := reg.Get(ctx, name)
		if getErr == nil && row != nil && filepath.IsAbs(row.Path) && filepath.Base(filepath.Clean(row.Path)) == name {
			return filepath.Clean(row.Path), nil
		}
	}
	root := filepath.Join(cfg.ChrootRoot, name)
	if filepath.Base(root) != name {
		return "", fmt.Errorf("invalid completion target %q", name)
	}
	return root, nil
}

func completionCatalog(cfg config.ChrootConfig, topic string, vals []string, out io.Writer) error {
	kind := "tool"
	if strings.Contains(topic, "addon") {
		kind = "addon"
	}
	c := catalog.Catalog{Kind: kind, Config: &cfg}
	distro, category := "", ""
	if len(vals) > 0 {
		distro = vals[0]
	}
	if len(vals) > 1 {
		category = vals[1]
	}
	if strings.Contains(topic, "categories") {
		rows, err := c.Categories(distro)
		if err != nil {
			return err
		}
		_, err = io.WriteString(out, strings.Join(rows, "\n"))
		return err
	}
	if strings.Contains(topic, "preview") {
		if len(vals) == 0 {
			return nil
		}
		entry, err := c.Get(vals[0])
		if err != nil {
			return err
		}
		_, err = fmt.Fprintf(out, "name: %s\nkind: %s\ndistros: %s\ncategories: %s\nscript: %s\n\n%s", entry.Name, entry.Kind, strings.Join(entry.Distros, ","), strings.Join(entry.Categories, ","), entry.Script, entry.Description)
		return err
	}
	entries, err := c.List(distro, category)
	if err != nil {
		return err
	}
	lines := make([]string, 0, len(entries))
	for _, entry := range entries {
		if strings.Contains(topic, "details") {
			categories := strings.Join(entry.Categories, ",")
			if categories == "" {
				categories = "uncategorized"
			}
			lines = append(lines, strings.Join([]string{entry.Name, categories, strings.Join(entry.Distros, ","), entry.Description}, "\t"))
		} else {
			lines = append(lines, entry.Name)
		}
	}
	_, err = io.WriteString(out, strings.Join(lines, "\n"))
	return err
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
