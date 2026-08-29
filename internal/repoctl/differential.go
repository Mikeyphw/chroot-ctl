package repoctl

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

func commandOutput(root string, env []string, name string, args ...string) ([]byte, error) {
	cmd := exec.Command(name, args...)
	cmd.Dir = root
	if env != nil {
		cmd.Env = append(os.Environ(), env...)
	}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("%s %v failed: %w\n%s", name, args, err, out)
	}
	return out, nil
}

// Differential runs the last Python-vs-Go parity probes kept during GO16.
// It is intentionally removed by GO17 together with the legacy Python tree.
func Differential() error {
	root, err := repoRoot()
	if err != nil {
		return err
	}
	if _, err = os.Stat(filepath.Join(root, "src", "chrootctl")); err != nil {
		return errors.New("legacy Python source is unavailable; GO16 differential gate cannot run")
	}
	py, err := exec.LookPath("python3")
	if err != nil {
		return errors.New("python3 is required only for the GO16 differential gate")
	}
	pyEnv := []string{"PYTHONPATH=" + filepath.Join(root, "src")}
	pyCompletion, err := commandOutput(root, pyEnv, py, "-m", "chrootctl.cli", "completion", "zsh")
	if err != nil {
		return err
	}
	goCompletion, err := commandOutput(root, nil, "go", "run", "./cmd/chrootctl", "completion", "zsh")
	if err != nil {
		return err
	}
	if !bytes.Equal(pyCompletion, goCompletion) {
		return fmt.Errorf("completion differential mismatch: python=%d bytes go=%d bytes", len(pyCompletion), len(goCompletion))
	}
	if _, err = commandOutput(root, pyEnv, py, "scripts/export-go-migration-contracts.py", "--check"); err != nil {
		return err
	}
	fmt.Printf("GO16 differential parity: completion=%d bytes, frozen contracts=no drift\n", len(goCompletion))
	return nil
}
