package module

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func deviceSnapshotFixture(t *testing.T) string {
	t.Helper()
	runtime := fakeRuntime(t)
	setEditionFixture(t, runtime, "standard")
	identity := &ReleaseIdentity{SourceCommit: strings.Repeat("a", 40), SourceTree: strings.Repeat("b", 40), DevtoolCommit: strings.Repeat("c", 40), BcloneLockSHA256: strings.Repeat("d", 64), GoCompilerVersion: "go1.27.2"}
	out := filepath.Join(t.TempDir(), "chrootctl")
	if err := Render(Options{OutputDir: out, NativeRuntimeDir: runtime, ReleaseIdentity: identity}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateInstalled(out); err != nil {
		t.Fatal(err)
	}
	return out
}
func runSnapshotFixture(t *testing.T, root string) ([]byte, error) {
	t.Helper()
	cmd := exec.Command("sh", "../../scripts/device/cc09-module-snapshot.sh")
	cmd.Env = append(os.Environ(), "CHROOTCTL_DEVICE_PROBE_FIXTURE=1", "CHROOTCTL_DEVICE_PROBE_ROOT="+root)
	return cmd.CombinedOutput()
}
func TestCC09DeviceSnapshotFixtureCannotClaimRealDeviceProof(t *testing.T) {
	root := deviceSnapshotFixture(t)
	out, err := runSnapshotFixture(t, root)
	if err != nil {
		t.Fatalf("fixture probe failed: %v %s", err, out)
	}
	var doc struct {
		Mode       string `json:"mode"`
		Edition    string `json:"edition"`
		Assessment string `json:"assessment"`
		SkybindR1  string `json:"skybindR1"`
		BootID     string `json:"bootId"`
	}
	if err := json.Unmarshal(out, &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Mode != "fixture" || doc.Edition != "standard" || doc.Assessment != "INSTALLED_SNAPSHOT_UNATTESTED" || doc.SkybindR1 != "NOT_TESTED" || doc.BootID != "fixture-not-device" {
		t.Fatalf("fixture falsely qualified: %+v", doc)
	}
	// An extra non-inventoried binary must prevent a passing snapshot.
	rclone := filepath.Join(root, "runtime", RuntimeABI, "rclone")
	if err := os.WriteFile(rclone, []byte("unexpected"), 0755); err != nil {
		t.Fatal(err)
	}
	out, err = runSnapshotFixture(t, root)
	if err == nil {
		t.Fatalf("unexpected rclone escaped standard detection: %s", out)
	}
	if err := os.Remove(rclone); err != nil {
		t.Fatal(err)
	}
	runtime := filepath.Join(root, "runtime", RuntimeABI, "chrootctl")
	b, err := os.ReadFile(runtime)
	if err != nil {
		t.Fatal(err)
	}
	b[len(b)-1] ^= 1
	if err := os.WriteFile(runtime, b, 0755); err != nil {
		t.Fatal(err)
	}
	if out, err = runSnapshotFixture(t, root); err == nil {
		t.Fatalf("runtime byte tamper escaped SHA verification: %s", out)
	}
}
