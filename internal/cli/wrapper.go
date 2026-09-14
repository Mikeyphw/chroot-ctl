package cli

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"chrootctl/internal/completion"
	"chrootctl/internal/redaction"
)

const (
	defaultWrapperName = "chc"
	wrapperMarker      = "# chrootctl-generated-wrapper:v1"
	completionMarker   = "# chrootctl-generated-completion:v1"
)

var wrapperNamePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)

type installFile struct {
	path    string
	data    []byte
	mode    os.FileMode
	kind    string
	existed bool
	backup  string
	staged  string
}

// InstallWrapper installs a thin, provenance-marked launcher. The launcher has
// no privilege logic of its own: it selects only active/root-managed chrootctl
// locations and delegates root policy to the generated Go CLI contract.
func InstallWrapper(inv Invocation, stdout, stderr io.Writer) int {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		home = os.Getenv("HOME")
	}
	if home == "" {
		return wrapperFailure(stderr, errors.New("cannot determine home directory for wrapper install"))
	}

	name := strings.TrimSpace(inv.String("wrapper_name"))
	if name == "" {
		name = defaultWrapperName
	}
	if !wrapperNamePattern.MatchString(name) {
		fmt.Fprintf(stderr, "chrootctl: invalid wrapper name %q; use [A-Za-z0-9][A-Za-z0-9._-]{0,63}\n", name)
		return 2
	}
	dir := strings.TrimSpace(inv.String("wrapper_dir"))
	if dir == "" {
		dir = filepath.Join(home, ".local", "bin")
	}
	dir, err = cleanInstallDir(dir)
	if err != nil {
		return wrapperFailure(stderr, err)
	}

	wrapperPath := filepath.Join(dir, name)
	if conflictsWithCurrentExecutable(wrapperPath) {
		return wrapperFailure(stderr, fmt.Errorf("refusing to replace the currently executing chrootctl path: %s", wrapperPath))
	}
	files := []installFile{{path: wrapperPath, data: []byte(wrapperScript()), mode: 0o755, kind: "wrapper"}}

	completionDir := strings.TrimSpace(inv.String("completion_dir"))
	if completionDir == "" && !inv.Bool("no_completion") {
		candidate := filepath.Join(home, ".local", "share", "zsh", "site-functions")
		if st, statErr := os.Stat(candidate); statErr == nil && st.IsDir() {
			completionDir = candidate
		}
	}
	if completionDir != "" && !inv.Bool("no_completion") {
		completionDir, err = cleanInstallDir(completionDir)
		if err != nil {
			return wrapperFailure(stderr, err)
		}
		text, genErr := completion.GenerateZshFor("chrootctl", name)
		if genErr != nil {
			return wrapperFailure(stderr, genErr)
		}
		files = append(files, installFile{
			path: filepath.Join(completionDir, "_chrootctl"),
			data: []byte(completionMarker + "\n" + text), mode: 0o644, kind: "completion",
		})
	}

	force := inv.Bool("force")
	for i := range files {
		existing, readErr := os.ReadFile(files[i].path)
		switch {
		case readErr == nil:
			files[i].existed = true
			marker := wrapperMarker
			if files[i].kind == "completion" {
				marker = completionMarker
			}
			if !bytesHaveMarker(existing, marker) && !force {
				return wrapperFailure(stderr, fmt.Errorf("refusing to replace unrelated %s %s; rerun with --force to acknowledge the collision", files[i].kind, files[i].path))
			}
		case errors.Is(readErr, os.ErrNotExist):
		case readErr != nil:
			return wrapperFailure(stderr, fmt.Errorf("inspect %s: %w", files[i].path, readErr))
		}
	}

	if inv.Globals.DryRun {
		for _, file := range files {
			action := "install"
			if file.existed {
				action = "replace"
			}
			fmt.Fprintf(stdout, "Would %s %s: %s\n", action, file.kind, file.path)
		}
		return 0
	}
	if err := transactionalInstall(files); err != nil {
		return wrapperFailure(stderr, err)
	}
	for _, file := range files {
		action := "Installed"
		if file.existed {
			action = "Updated"
		}
		fmt.Fprintf(stdout, "%s %s: %s\n", action, file.kind, file.path)
	}
	fmt.Fprintf(stdout, "Use: %s --help\n", name)
	return 0
}

func wrapperFailure(stderr io.Writer, err error) int {
	fmt.Fprintln(stderr, "chrootctl:", redaction.String(err.Error()))
	return 1
}
func bytesHaveMarker(data []byte, marker string) bool {
	text := string(data)
	return strings.HasPrefix(text, marker+"\n") || strings.Contains(text[:min(len(text), 256)], marker)
}
func cleanInstallDir(dir string) (string, error) {
	if strings.HasPrefix(dir, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		dir = filepath.Join(home, strings.TrimPrefix(dir, "~/"))
	}
	if !filepath.IsAbs(dir) {
		return "", fmt.Errorf("wrapper install directory must be absolute: %s", dir)
	}
	return filepath.Clean(dir), nil
}
func conflictsWithCurrentExecutable(path string) bool {
	exe, err := os.Executable()
	if err != nil {
		return false
	}
	cleanPath, _ := filepath.Abs(path)
	cleanExe, _ := filepath.Abs(exe)
	if cleanPath == cleanExe {
		return true
	}
	pResolved, pErr := filepath.EvalSymlinks(cleanPath)
	eResolved, eErr := filepath.EvalSymlinks(cleanExe)
	return pErr == nil && eErr == nil && pResolved == eResolved
}

func transactionalInstall(files []installFile) (err error) {
	createdDirs := map[string]bool{}
	committed := 0
	committedAll := false
	defer func() {
		if err == nil || committedAll {
			return
		}
		for i := committed - 1; i >= 0; i-- {
			_ = os.Remove(files[i].path)
			if files[i].backup != "" {
				_ = os.Rename(files[i].backup, files[i].path)
			}
		}
		for i := committed; i < len(files); i++ {
			if files[i].backup != "" {
				_ = os.Rename(files[i].backup, files[i].path)
			}
		}
		for _, file := range files {
			if file.staged != "" {
				_ = os.Remove(file.staged)
			}
		}
		for dir := range createdDirs {
			_ = os.Remove(dir)
		}
	}()

	for i := range files {
		dir := filepath.Dir(files[i].path)
		if _, statErr := os.Stat(dir); errors.Is(statErr, os.ErrNotExist) {
			if mkErr := os.MkdirAll(dir, 0o755); mkErr != nil {
				return mkErr
			}
			createdDirs[dir] = true
		} else if statErr != nil {
			return statErr
		}
		staged, stageErr := stageInstallFile(dir, filepath.Base(files[i].path), files[i].data, files[i].mode)
		if stageErr != nil {
			return stageErr
		}
		files[i].staged = staged
	}
	for i := range files {
		if files[i].existed {
			backup, backupErr := reserveSibling(filepath.Dir(files[i].path), "."+filepath.Base(files[i].path)+".chrootctl-backup-")
			if backupErr != nil {
				return backupErr
			}
			if renameErr := os.Rename(files[i].path, backup); renameErr != nil {
				return renameErr
			}
			files[i].backup = backup
		}
		if renameErr := os.Rename(files[i].staged, files[i].path); renameErr != nil {
			return renameErr
		}
		files[i].staged = ""
		committed++
		if syncErr := syncDir(filepath.Dir(files[i].path)); syncErr != nil {
			return syncErr
		}
	}
	committedAll = true
	var cleanupErr error
	for i := range files {
		if files[i].backup != "" {
			backup := files[i].backup
			files[i].backup = ""
			if removeErr := os.Remove(backup); removeErr != nil && cleanupErr == nil {
				cleanupErr = fmt.Errorf("cleanup backup %s: %w", backup, removeErr)
			}
		}
	}
	return cleanupErr
}

func stageInstallFile(dir, base string, data []byte, mode os.FileMode) (string, error) {
	tmp, err := os.CreateTemp(dir, "."+base+".chrootctl-stage-")
	if err != nil {
		return "", err
	}
	name := tmp.Name()
	ok := false
	defer func() {
		if !ok {
			_ = os.Remove(name)
		}
	}()
	if _, err = tmp.Write(data); err != nil {
		_ = tmp.Close()
		return "", err
	}
	if err = tmp.Chmod(mode); err != nil {
		_ = tmp.Close()
		return "", err
	}
	if err = tmp.Sync(); err != nil {
		_ = tmp.Close()
		return "", err
	}
	if err = tmp.Close(); err != nil {
		return "", err
	}
	ok = true
	return name, nil
}
func reserveSibling(dir, pattern string) (string, error) {
	f, err := os.CreateTemp(dir, pattern)
	if err != nil {
		return "", err
	}
	name := f.Name()
	if err = f.Close(); err != nil {
		_ = os.Remove(name)
		return "", err
	}
	if err = os.Remove(name); err != nil {
		return "", err
	}
	return name, nil
}
func syncDir(dir string) error {
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}

func wrapperScript() string {
	return `#!/system/bin/sh
` + wrapperMarker + `
# Thin launcher: privilege decisions belong exclusively to the Go CLI contract.
set -eu
for candidate in \
  /system/bin/chrootctl \
  /data/adb/modules/chrootctl-magisk/system/bin/chrootctl \
  /data/adb/ksu/modules/chrootctl-magisk/system/bin/chrootctl
do
  if [ -x "$candidate" ]; then
    exec "$candidate" "$@"
  fi
done
echo "chc: no active trusted chrootctl runtime found" >&2
exit 127
`
}
