package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"chrootctl/internal/validation"
)

// RewriteChrootOverride atomically renames or removes one persisted per-chroot
// override. It preserves every unrelated top-level key and refuses ambiguous
// destination ownership. A missing config file is a no-op only when there is no
// override to rewrite.
func RewriteChrootOverride(path, oldName, newName string, remove bool) (bool, error) {
	oldSafe, err := validation.ChrootName(oldName)
	if err != nil {
		return false, err
	}
	newSafe := ""
	if !remove {
		newSafe, err = validation.ChrootName(newName)
		if err != nil {
			return false, err
		}
	}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	payload, err := decodeObject(data)
	if err != nil {
		return false, err
	}
	if err = validatePayloadKeys(payload, topLevelConfigKeys, "config"); err != nil {
		return false, err
	}
	raw, ok := payload["chroot_overrides"]
	if !ok || raw == nil {
		return false, nil
	}
	overrides, ok := raw.(map[string]any)
	if !ok {
		return false, fmt.Errorf("chroot_overrides must be an object")
	}
	value, exists := overrides[oldSafe]
	if !exists {
		return false, nil
	}
	if !remove {
		if _, conflict := overrides[newSafe]; conflict {
			return false, fmt.Errorf("chroot override already exists for destination identity: %s", newSafe)
		}
		overrides[newSafe] = value
	}
	delete(overrides, oldSafe)
	payload["chroot_overrides"] = overrides
	return true, writeConfigObjectAtomic(path, payload)
}

func writeConfigObjectAtomic(path string, payload map[string]any) error {
	if path == "" {
		return fmt.Errorf("config path is empty")
	}
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	mode := os.FileMode(0600)
	if st, err := os.Stat(path); err == nil {
		mode = st.Mode().Perm()
	}
	tmp, err := os.CreateTemp(dir, ".chrootctl-config-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	cleanup := true
	defer func() {
		if cleanup {
			_ = os.Remove(tmpName)
		}
	}()
	if err = tmp.Chmod(mode); err != nil {
		_ = tmp.Close()
		return err
	}
	enc := json.NewEncoder(tmp)
	enc.SetIndent("", "  ")
	if err = enc.Encode(payload); err != nil {
		_ = tmp.Close()
		return err
	}
	if err = tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	if err = os.Rename(tmpName, path); err != nil {
		return err
	}
	cleanup = false
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}
