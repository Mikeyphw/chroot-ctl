package services

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

func ptrText(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

type DirectoryUsage struct {
	Bytes         int64
	Errors        int
	SkippedMounts int
}

func (u DirectoryUsage) Reliable() bool { return u.Errors == 0 && u.SkippedMounts == 0 }

func directorySize(root string) int64 { return directoryUsage(root).Bytes }

func directoryUsage(root string) DirectoryUsage {
	var usage DirectoryUsage
	rootInfo, err := os.Lstat(root)
	if err != nil {
		if !os.IsNotExist(err) {
			usage.Errors++
		}
		return usage
	}
	rootStat, _ := rootInfo.Sys().(*syscall.Stat_t)
	var rootDevice uint64
	if rootStat != nil {
		rootDevice = uint64(rootStat.Dev)
	}
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, e error) error {
		if e != nil {
			usage.Errors++
			return nil
		}
		info, e := d.Info()
		if e != nil {
			usage.Errors++
			if d.IsDir() && path != root {
				return filepath.SkipDir
			}
			return nil
		}
		if path != root && d.IsDir() && rootDevice != 0 {
			if st, ok := info.Sys().(*syscall.Stat_t); ok && uint64(st.Dev) != rootDevice {
				usage.SkippedMounts++
				return filepath.SkipDir
			}
		}
		if info.Mode().IsRegular() {
			usage.Bytes += info.Size()
		}
		return nil
	})
	return usage
}
func contained(root, target, label string) (string, error) {
	a, e := filepath.Abs(root)
	if e != nil {
		return "", e
	}
	b, e := filepath.Abs(target)
	if e != nil {
		return "", e
	}
	rel, e := filepath.Rel(a, b)
	if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("%s escapes configured root: %s", label, target)
	}
	return b, nil
}
func validateRegisteredTargetPath(configuredRoot, name, target string) (string, error) {
	if !filepath.IsAbs(target) {
		return "", fmt.Errorf("registered chroot path must be absolute: %s", target)
	}
	clean := filepath.Clean(target)
	if clean == string(filepath.Separator) || clean == filepath.Clean(configuredRoot) {
		return "", fmt.Errorf("registered chroot path must identify one chroot, not a management root: %s", target)
	}
	if filepath.Base(clean) != name {
		return "", fmt.Errorf("registered chroot path basename %q does not match identity %q", filepath.Base(clean), name)
	}
	parent := filepath.Dir(clean)
	if parent == string(filepath.Separator) {
		return "", fmt.Errorf("registered chroot path must not be a filesystem-root child: %s", target)
	}
	base := filepath.Base(clean)
	if base == ".snapshots" || base == ".chrootctl" {
		return "", fmt.Errorf("registered chroot path points at reserved management storage: %s", target)
	}
	return clean, nil
}

func diskUsage(path string) (total, used, free uint64) {
	for {
		var st syscall.Statfs_t
		if syscall.Statfs(path, &st) == nil {
			return st.Blocks * uint64(st.Bsize), (st.Blocks - st.Bfree) * uint64(st.Bsize), st.Bavail * uint64(st.Bsize)
		}
		parent := filepath.Dir(path)
		if parent == path {
			return
		}
		path = parent
	}
}
func uniqueStrings(in []string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, x := range in {
		if x != "" && !seen[x] {
			seen[x] = true
			out = append(out, x)
		}
	}
	return out
}
func exists(path string) bool { _, e := os.Stat(path); return e == nil }
